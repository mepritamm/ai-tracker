# Job summary in the session header

Branch: `worktree-job-summary-header` (worktree `.claude/worktrees/job-summary-header`), base `personal/main` @ 251a98a.

## Contract (verbatim)

> I want these small summary folded into the tracker app itself [screenshot 1: Claude Code background-job list — "Ready for review / Needs input / Working / Completed" groups, one-line summary per job] [screenshot 2: tracker session header showing the last prompt line under the title] add a config to set asking for what to show the last narration message or this kind of summary, summary by default, build a technical plan, do an adversial review for the same with opus and update the plan with the review comments fixed into the plan and then implement the changes via /tracker-gap and once thats done run /tracker-push

| # | Clause | Status |
|---|---|---|
| C1 | Job-list one-line summary shown in the tracker (session header) | implemented + final review fixed (test_job_headline: HeadlineTests.test_summary_from_job_detail_direct_dir, test_job_found_via_resume_session_id, test_band_mapping_each_state, test_dead_blocked_job_keeps_text_drops_pill, ConfigRoundtripTests.test_http_job_session_and_served_page; test_header_and_cost_ui: test_cr_header_line_renders_headline_text_and_band_pill, ClassicHeadlineTests.test_classic_overview_renders_headline) |
| C2 | Config: last narration message vs. summary | implemented + final review fixed (test_job_headline: ConfigTests.test_default_mode_is_summary, HeadlineTests.test_narration_mode_ignores_job, ConfigRoundtripTests.test_config_post_roundtrip; test_header_and_cost_ui: test_config_dialog_has_header_line_row) |
| C3 | Summary is the default | implemented + final review fixed (test_job_headline: ConfigTests.test_default_mode_is_summary, HeadlineTests.test_missing_job_file_falls_back_to_narration, AuggieHeadlineTests.test_auggie_headline_is_narration; selfcheck headline assertions) |
| C4 | Technical plan (opus) | not discharged |
| C5 | Adversarial review (opus), fixes folded into the plan | not discharged |
| C6 | Implemented via /tracker-gap (evals + unit tests, both providers) | not discharged |
| C7 | /tracker-push | not discharged |

### Contract addendum (verbatim, mid-turn)

> in the same plan add a cost calculator which shows how much we have burned in that particular session and upon clicking on that very cost tab, we could how much we have saved by caching and how much the agents have burned

| # | Clause | Status |
|---|---|---|
| C8 | Cost chip in the session header: $ burned in this session | implemented + final review fixed (test_session_cost: PriceTests.*, ClaudeCostTests.test_cost_last_usage_per_message_id_wins, test_cost_state_reported_only_when_after_last_usage, AuggieCostTests.*, SeamTests.*; test_header_and_cost_ui: test_cr_cost_chip_is_button_and_opens_modal, test_classic_cost_chip_present, test_phone_css_keeps_only_cost_chip; selfcheck cost assertions, both providers) |
| C9 | Clicking the cost chip shows $ saved by prompt caching | implemented + final review fixed (test_session_cost: PriceTests.test_cache_savings_gross_premium_net, AuggieCostTests.test_auggie_recorded_cost_and_subagents; test_header_and_cost_ui: test_cr_cost_chip_is_button_and_opens_modal, test_cost_modal_reported_line) |
| C10 | Clicking the cost chip shows $ burned by the session's agents (sub-agents) | implemented + final review fixed (test_session_cost: ClaudeCostTests.test_agents_cost_split_and_rows, AuggieCostTests.test_auggie_recorded_cost_and_subagents; test_header_and_cost_ui: test_cr_cost_chip_is_button_and_opens_modal) |

### Contract addendum 2 (verbatim, mid-turn; screenshot: Narration modal with a "**Draft reply for Bharadwaj** (not posted): > No direct ViDA impact. …" paragraph)

> this kind of draft reply should always come up with a copy option like we show it for the code copy such that it can easily be copy and pasted into the slack or any other places

| # | Clause | Status |
|---|---|---|
| C11 | Draft replies in narration always get a copy button (same affordance as code-block copy), copying clean paste-ready text | implemented + final review fixed (test_draft_copy: test_bharadwaj_shape_gets_one_copy_button, test_heading_label_then_blank_then_quote, test_negatives_no_button, test_plain_blockquote_renders_as_blockquote_without_button, test_code_fence_keeps_single_button_inside_draft_doc, test_fence_inside_draft_quote, test_copycode_uses_cpsrc_and_textarea_fallback, WiringTests; red-first proven) |

### Process (verbatim)

> single plan single review single review addressed in plan --> opus and implement with another agent then final adversial review with opus and fix all the issues found directly all implementation and fixes goes with /tracker-gap and then /tracker-push

## Data facts (confirmed from real files, 2026-11-13)

- `~/.claude/jobs/<sid[:8]>/state.json` exists **only for background jobs** (110 of them on this machine).
- Keys: `state` ∈ {working, blocked, done, failed, stopped}, `detail` (the one-line summary the job list shows),
  `sessionId` (full UUID), `needs`, `suggestedReply`, `output` ({result: ...} when done), `updatedAt`, `name`, `linkScanPath`.
- `timeline.jsonl`: `{at, state, detail, text}` per transition.
- Ordinary (non-job) Claude sessions and Auggie sessions have no job file → need a fallback.

## Plan

Author: opus planner, 2026-11-13. **Revision 2 (2026-11-13): folds in the review's accepted fixes
F1–F3, F5–F8, F10, F11 exactly as the orchestrator's verdict table scopes them; F4 rejected, F9
no change.** Covers C1–C3 (A: header summary + config), C8–C10 (B: cost) and C11 (C: draft-reply
copy) as ONE plan. Every `path:line` below was read in this worktree at `251a98a`; line numbers
drift — re-read the region before editing (conventions rule 12).

### 0. Facts re-derived from disk for this plan (beyond the "Data facts" section)

**Which header is "the header".** The screenshot (title, Rename/Pin, one prompt line, then
files/commands/reads/commits/tests/tokens/branch chips) is the **Control Room** detail header, not the
classic one: skeleton `aitracker/web/ext_cr_detail.js:1360-1393` (`.crd-goal` h1, `.crd-rename`,
`.crd-pin`, `.crd-goalline`, `.crd-statchips`), filled by `renderHeader()` `ext_cr_detail.js:2357`.
The prompt line is `.crd-goalline` ← `session.overview.goal` (`ext_cr_detail.js:2455-2463`), which is
`requests[-1]["text"]` (`aitracker/overview.py:19`; Auggie `auggie.py:782`). The chips are
`statChipsHtml()` `ext_cr_detail.js:1033-1067`. The classic view (`app.js render()` `:1832`) has no
such line (its goal lives in the Overview card `app.js:1979`), but does have a chip row
(`app.js:1887-1891`) — it gets the cost chip too (parity, `tests/test_view_parity.py`).

**Job dir key.** All 111 readable `~/.claude/jobs/*/state.json`: dir name == `daemonShort` ==
`sessionId[:8]` (111/111). BUT 13/111 have `resumeSessionId != sessionId`, and for those the
transcript can live under the **resume** id (`31cd62a0` → transcript `a4eafc9a…` only; `86c95cd1` →
both exist). So `sid[:8]` alone misses resumed jobs. The existing reader `_blocked_jobs()`
(`providers/claude.py:720-744`) already maps **both** `sessionId` and `resumeSessionId` — the plan
does the same. 35 dirs have no `state.json` (only `tmp/`) or are `.draft-*` files → ignored.

**state.json shapes seen (111):** (state, needs?, output.result?, tempo) →
done/no/yes/idle 46 · blocked/yes/no/blocked 39 · blocked/yes/yes/blocked 12 ·
blocked/no/yes/idle 1 · blocked/no/no/idle 3 · working/no/no/active 4 · working/yes/no/blocked 1 ·
done/no/no/idle 3 · failed 1 · stopped 1. `needs` is a string when present (a `block.questions[]`
object also appears once). `detail` is always a string. `tokens` (int) is present on 104 — NOT used
(no model split, can't be priced).

**Claude Code's own grouping** (from the installed CLI bundle
`~/.local/share/claude/versions/2.1.323`, minified):
`var tr=["review","blocked","working","done"],Lo={review:"Ready for review",blocked:"Needs input",working:"Working",done:"Completed"}`,
row `{…band:<fn>(h.state),state:h.state.state,needs:h.state.needs,outcome:pw(h.state.state)…}`,
and the job-list group function (verbatim, minified):
`function Is(h,w,k){if(k==="busy")return"working";if(h.activity==="failure")return"done";if(h.activity==="stopped")return"done";if(k==="waiting")return"blocked";if(!Sae(h.state)&&Rn(h.state.children).some((P)=>{let T=w?.get(P.href);if(T?.state!=="OPEN")return!1;let M=FAr(T);return M==="error"||M==="warning"&&T.review!=="APPROVED"}))return"review";if(h.activity==="success")return"done";if(h.state.tempo==="blocked")return"blocked";return"working"}`
with `pw(e){if(e==="done")return"success";if(e==="failed")return"failure";if(e==="stopped")return"stopped";return null}`
and `activity` = `pw(state)` only when `tempo!=="active"` (helper `kn`). So:
- **"Ready for review" is NOT derivable from disk**: it fires only when a job's child PR (`state.children[].href`)
  is OPEN with failing/warning checks and not approved — PR state the CLI fetches from GitHub. The tracker
  has no outbound network (conventions rule 6), so it **never emits `review`** (honest, documented).
- `k` (`busy`/`waiting`) is the live worker's in-memory status — not on disk; `tempo` is the on-disk stand-in.

**Band mapping the tracker uses (mirrors `Is` minus the two non-disk inputs):**

| condition on state.json | band | label |
|---|---|---|
| `state` ∈ {done, failed, stopped} and `tempo != "active"` | done | Completed (pill adds " · failed"/" · stopped" from raw `state`) |
| else `tempo == "blocked"` | blocked | Needs input |
| else | working | Working |

On today's 111 files that yields Completed 51 · Needs input 52 · Working 8 (incl. the 1
blocked/no-needs/idle and 3 blocked/no/no/idle rows — the CLI shows those as Working too, unless its
live worker reports `waiting`). **Many of those are dead** (F3): 51/111 are `blocked`/`tempo:blocked`,
several last updated months ago (e.g. `99fd239f`, 2026-08-08), with no live worker in the daemon
roster. The header's existing `waiting` flag/state pill is live-gated through `_blocked_jobs`
(`claude.py:720`, called at `:1999`, feeds `waiting` at `:2023`), so the band pill must use the
same live gate (A2).

**Usage shape (1,031 files: 400 newest transcripts + 800 `agent-*.jsonl`, 74,269 usage blocks).**
`message.usage` = `input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens,
cache_creation{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}, service_tier, speed,
inference_geo, iterations[], server_tool_use, output_tokens_details, fallback_credit` — identical in
transcripts and agent files. Values seen: `speed` ∈ {standard, absent}; `service_tier` ∈ {standard,
asap(4), absent}; `inference_geo` ∈ {global, not_available, "", absent} (no `"us"` → no 1.1× uplift
needed today).
- **Duplicate lines per message id.** One assistant message spans several JSONL lines sharing
  `message.id` (no id has >1 `requestId`; 0 id-less usage lines). Their usage is NOT identical:
  `output_tokens` is monotone non-decreasing across the lines (first line often `output_tokens: 1`),
  input/cache fields are constant. `_transcript_pass` keeps the **first** line per id
  (`claude.py:1677,1719-1727`), as do `_hb_agent_line` (`:1093-1102`) and the heartbeat. Token
  sample (transcripts + agent files): first-seen output 28,922,087 vs last-seen 29,850,972. The
  review (F10) re-ran this on 100 main transcripts and found first-seen $ == last-seen $ to the
  cent there, so the $ effect is not demonstrated for main transcripts; **cost still uses the LAST
  usage per id** because it is the complete figure, and the existing `tokens` count is left as is.
- **Claude Code writes its own cost at exit** (F1). Lines `{"type":"cost-state","sessionId",
  "totalCostUSD","hasUnknownModelCost","modelUsage":{<model>:{inputTokens,outputTokens,thinkingTokens,
  cacheReadInputTokens,cacheCreationInputTokens,cacheCreationEphemeral5mInputTokens,
  cacheCreationEphemeral1hInputTokens,webSearchRequests,costUSD}},totalDuration,…}` appear in 117 of
  the 232 newest transcripts (re-checked for revision 2); the last one sits at EOF in 100 (the
  rest are mid-file = resumed later). It is cumulative and its total **includes sub-agents**. It is
  written at process exit, so a live session has no fresh one. Recomputing a real record with the
  table above matches exactly: opus-5-5 {in 1,598, out 45,779, read 6,517,904, w1h 226,002} →
  $4.0335688 (record says `costUSD: 4.0335688`; `outputTokens` already includes `thinkingTokens`).
  Known gap kept visible (not explained by plan or review): for some sessions the CLI total and
  main+agents recompute diverge widely (`4405110a` $106.86 vs $3.87; `7d44ec42` $12.20 vs $61.53).
- **Forked/continued transcripts copy history** (F6): 1,493 of 14,976 usage `message.id`s appear in
  more than one main transcript (e.g. `eed23597`/`b81bda8c` share 330). Agent files never share an
  id with their main transcript or each other (review: 0 of 2,082), so main + agents doesn't double
  count inside one session.
- **cache_creation split disagreement.** 66,227 equal; 297 have top-level
  `cache_creation_input_tokens>0` but a zero 5m/1h breakdown (all `openai/*` via OpenRouter);
  4 have top-level `0` but breakdown `>0` (claude-opus-5-5; `iterations[0]` agrees with the
  breakdown). Rule: if `5m+1h > 0` use the breakdown; else charge the top-level figure as 5m.
- **Distinct `message.model` values** (count of usage lines): claude-opus-5-5 27,462 ·
  claude-opus-5 14,135 · claude-sonnet-5-5 7,858 · claude-haiku-5-5 6,424 · claude-opus-4-8 6,293 ·
  claude-sonnet-5 5,883 · claude-haiku-4-5-20251001 3,971 · claude-sonnet-4-6 1,324 ·
  deepseek/deepseek-v4.1-flash-1017 380 · openai/gpt-6-luna 237 · claude-fable-5-1 159 ·
  `<synthetic>` 75 · openai/gpt-6.1-sol 68.
- **Auggie** (`~/.augment/sessions/*.json`, 88 files, 3,714 `token_usage` blocks): keys
  `input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens` (+ context
  sizing fields; **no 5m/1h split, no message id**); `exchange.model_id` ∈
  {claude-opus-4-7-500k 3,650, claude-opus-4-8 31, None 33}. `util.model_version("claude-opus-4-7-500k")`
  → None (the `500k` part is non-numeric).
- **Auggie records what it billed** (F2, re-checked for revision 2): 3,714 of 3,717 exchanges with
  response nodes carry `response_nodes[].billing_metadata.cost_usd` — always a **string** (e.g.
  `"1.832267125"`), on a different response node from `token_usage`; 87 of 88 sessions have a
  top-level `subAgentCostUsd` (a number). The review measured recorded/list-price = exactly 1.300
  for opus-4-7 over 3,681 exchanges, i.e. Augment's billed price, not Anthropic's list price.

**Prices** — fetched 2026-11-13 from `https://platform.claude.com/docs/en/about-claude/pricing`
($/MTok, standard tier, global). **The brief's "cache read = 0.1× input" is wrong for three of the
models in use** (Opus 5.5 and Sonnet 5.5 are 0.05×, Fable 5.1 is 0.025×), so the table stores all
five columns explicitly instead of deriving them:

| family, version | input | write 5m | write 1h | cache read | output |
|---|---|---|---|---|---|
| opus 5.5 | 4 | 5 | 8 | 0.20 | 20 |
| opus 5 | 5 | 6.25 | 10 | 0.50 | 25 |
| opus 4.8 / 4.7 / 4.6 / 4.5 | 5 | 6.25 | 10 | 0.50 | 25 |
| sonnet 5.5 | 2 | 2.50 | 4 | 0.10 | 10 |
| sonnet 5 | 2 | 2.50 | 4 | 0.20 | 10 |
| sonnet 4.6 / 4.5 | 3 | 3.75 | 6 | 0.30 | 15 |
| haiku 5.5 (prompt ≤ 100,000) | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| haiku 5.5 (prompt > 100,000) | 0.50 | 0.625 | 1 | 0.05 | 2.50 |
| haiku 4.5 | 1 | 1.25 | 2 | 0.10 | 5 |
| fable 5.1 | 10 | 12.50 | 20 | 0.25 | 50 |

Page rules that matter: "Claude 4.6 and later models (except Claude Haiku 5.5) include the full 1M
token context window at standard pricing" (no long-context tier for anything above but Haiku 5.5);
Haiku 5.5's prompt length "counts all of its input tokens, including cache reads and cache writes",
per request; fast mode is premium-priced (not seen on disk); `inference_geo:"us"` is 1.1× (not seen).

**Draft replies in real narration (C11)** — every assistant `text` block in all 231 transcripts
scanned for a lead label (a line starting `**…draft…**` or a `#` heading containing "draft"):
13 hits. **All 7 genuine drafts are a label line followed (optionally after one blank line) by a
`>` blockquote run**: "**Draft reply for Bharadwaj** (not posted):", "**Draft 1: reply to Manu**
(Slack DM…)", "**Draft 2: your section for the POC results doc**", "## 3. Slack message draft (for
review — not posted)", "## Ticket draft for the `dw-vida-ai` fixes", "**Draft post**, to go out
after…", "**Draft Jira comment for AIO-4183.** Posting it…". The 6 non-drafts are a label followed by
a list, a bold paragraph or a mermaid fence ("**Draft plan:**" + numbered list, "**P2 is green… the
PR stays draft.**", "**What BT's item #3 changed in the draft:**", "## 4. What the saved draft task
looked like…" + mermaid, "**AIO-4258 + AIO-4282: both real, two draft comments written.**" + list,
a bold PR link). 427 further blocks mention "draft" only in prose; 62 contain some `>` line (quoted
prompts etc., no draft label). **Why the screenshot showed an inline "> ":** `mdBlock()` has no
blockquote branch at all — the paragraph loop (`app.js:218-220`) swallows the label line and the `>`
lines into one `<p>` joined by spaces. Auggie narration goes through the same renderers (same
`narrative[]` shape, same `openText`/`mdBlock`/`mdHtml`), so it inherits C11 for free.

---

### A. Job summary in the session header (C1, C2, C3)

**A1. Config knob — `HEADER_LINE`** (`aitracker/config.py`, the existing config.json mechanism; no new one).
- `EDITABLE` (`config.py:207-209`): append `"HEADER_LINE"`.
- `VALIDATORS` (`:251-271`): `"HEADER_LINE": _v_enum(("summary", "narration")),`.
- New resolver beside `resolve_gateway` (`:436`), same shape (no env var — config.json > default):
  ```python
  def resolve_header_line(overrides):
      """What the detail header's one line shows: "summary" (a background job's own one-line
      status from ~/.claude/jobs, falling back to narration when the session has no job) or
      "narration" (the latest narration message, always). config.json > built-in "summary"."""
      v = overrides.get("HEADER_LINE")
      return v if v in ("summary", "narration") else "summary"
  ```
- `_RESOLVERS` (`:502`) + `_PLAIN_ATTR_KEYS` (`:523`) + module global `HEADER_LINE = resolve_header_line({})`
  (`:532-540` block). It is then live exactly like `GATEWAY`: `apply_overrides()` (`:543`) repoints it
  at startup (`server.py:918`) and on every GET/POST `/api/config` (`server.py:420-421, 613-616`).
  Not in `RESTART_REQUIRED`. Consumers read `config.HEADER_LINE` at call time.
- Config dialog row (`aitracker/web/ext_cr_dialogs.js`): `_ENVCHIP` (`:859`) add `HEADER_LINE: null`;
  in the `'Interface'` section (`:1245`), after the Live-window row (`:1326`):
  `serverRow('Header line', 'HEADER_LINE', 'What the line under the session name shows: a background job\'s one-line status (falls back to the latest narration when the session isn\'t a job), or always the latest narration.', function (value, onCommit) { return segmented([['summary','Job summary'],['narration','Narration']], value || 'summary', onCommit); })`
  — same `segmented` control `GATEWAY` uses (`:1358-1362`). Open pages pick the change up on the next
  2 s poll (the server resolves it per request; no client cache).

**A2. Job reader — Claude only** (`aitracker/providers/claude.py`, next to `_blocked_jobs` `:720`).
```python
def _job_fields(path):
    """Pure fn of one state.json (cached via util.file_pass): only the fields the header needs."""
    with open(path) as fh:
        st = json.load(fh)
    if not isinstance(st, dict):
        return None
    n = st.get("needs")
    if isinstance(n, dict):
        n = n.get("question")
    res = (st.get("output") or {}).get("result") if isinstance(st.get("output"), dict) else None
    s = lambda v: v.strip() if isinstance(v, str) and v.strip() else ""
    return {"ids": [x for x in (st.get("sessionId"), st.get("resumeSessionId")) if isinstance(x, str) and x],
            "state": s(st.get("state")), "tempo": s(st.get("tempo")), "detail": s(st.get("detail"))[:400],
            "needs": s(n)[:400], "result": s(res)[:400], "updated": s(st.get("updatedAt"))}

def job_for(sid, live):
    """The background job whose sessionId OR resumeSessionId is `sid`, as the header shape, else None.
    Direct dir sid[:8] first (the common case, O(1)); else scan JOBS_DIR (resumed jobs). `live` is
    _live_daemon_shorts(): a non-"done" band whose job dir isn't live loses its pill. Never raises."""
```
- Lookup: try `JOBS_DIR/sid[:8]/state.json`; accept only if `sid in f["ids"]` (an 8-char prefix
  collision must not borrow a stranger's job). Miss → `os.listdir(JOBS_DIR)`, skip names failing
  `safe_path_component`, read each `state.json` through `file_pass("claude.jobstate", p, _job_fields)`
  (stat-validated per call, parse only on change — `util.py:550`), first whose `ids` contains `sid`.
  Any `OSError`/`ValueError` per file → skip. Cost per poll ≈ one `listdir` + ~111 `stat`s + unpickles
  of 7-key dicts; only hit when the direct lookup misses (i.e. every non-job session). That is the
  whole design — **no memo** (F7: a memo keyed on `JOBS_DIR`'s mtime would miss a resume, which
  rewrites `<short>/state.json` and bumps only `<short>`'s mtime; the per-file `file_pass` cache
  already avoids re-parsing).
- Return shape (server owns the label policy — `BAND_LABEL` dict beside it):
  `{"band": "blocked"|"working"|"done", "label": "Needs input"|"Working"|"Completed",
    "detail": str, "needs": str, "result": str, "state": "<raw state>", "updated": "<iso>"}`
  with the band mapping table in §0 (`_job_band(f)` — a 5-line function; `"review"` is never
  produced, see §0). `detail` empty → fall back to
  `needs`, then `result`, else the whole job is treated as "no summary" (→ narration fallback).
- Staleness (F3): the **text** is kept for every job (a dead job's `detail` is still its right
  summary), but the **band pill** uses the same live gate as `_blocked_jobs` (`claude.py:720-744`):
  in `job_for`, after `_job_band(f)`, `if band != "done" and short not in live: band = label = None`
  (`short` = the job dir name the match came from; `state` is kept). `done` keeps "Completed" forever.
  So a months-dead `blocked` job never shows "Needs input" while the same header's `waiting`/state
  pill (live-gated, `:1999,:2023`) says idle.
- `parse_session()` result dict (`claude.py:2000-2058`): add `"job": job_for(sid, _live_daemon_shorts()),`
  (sid at `:1917`; `_live_daemon_shorts` `:594` — a second small roster read beside the one inside
  `_blocked_jobs()` at `:1999`; not refactored to share it, to keep `_blocked_jobs` untouched).

**A3. The shared seam — `registry.parse_any()`** (`aitracker/registry.py:160`). After the existing
`setdefault`s (`:199-208`):
```python
d.setdefault("job", None)                       # Auggie/Augment ext: no job concept → honest None
d["headline"] = headline(d, config.HEADER_LINE)
```
`headline()` lives in `aitracker/overview.py` (the module that already builds `overview.goal/now`;
`HL_`-free single function, no new imports):
```python
def headline(d, mode):
    """The detail header's one line, per config HEADER_LINE. Server policy; the SPA only renders it."""
    j = d.get("job") or {}
    text = j.get("detail") or j.get("needs") or j.get("result") or ""
    if mode == "summary" and text:
        return {"mode": mode, "source": "job", "text": text, "band": j.get("band"), "label": j.get("label"),
                "updated": j.get("updated") or None}
    n = (d.get("narrative") or [{}])[0].get("text") or d.get("message") or ""
    return {"mode": mode, "source": "narration" if n else "none", "text": n[:2000],
            "band": None, "label": None, "updated": (d.get("narrative") or [{}])[0].get("t")}
```
`narrative` is newest-first in every provider (`claude.py:2039`, `auggie.py:767`, augment_ext `:285`)
and `parse_any` runs before `/api/session` pages it (`server.py:509-512`), so `[0]` is the newest.
Exact JSON: `"headline": {"mode": "summary"|"narration", "source": "job"|"narration"|"none",
"text": str, "band": str|null, "label": str|null, "updated": str|null}` and
`"job": {band,label,detail,needs,result,state,updated} | null`.

**A4. Render** (`aitracker/web/ext_cr_detail.js` `renderHeader`, `:2449-2463` only).
Replace `var goalText = (session.overview && session.overview.goal) || "";` with
`var hl = session.headline || {}; var goalText = hl.text || "";`, and prepend the band label as a
small pill **inside the same line** so it wraps/clamps with it (no new row):
`goalEl.innerHTML = (hl.label ? '<span class="crd-hl-band crd-hl-' + esc(hl.band) + '">' + esc(hl.label) + '</span> ' : '') + (typeof md === "function" ? md(goalText) : esc(goalText));`
`goalEl.title` gains `" · " + hl.label` when present. Keep `data-act="toggle-goal"` and the 3-line
clamp (`ext_cr_detail.css:223-243`). CSS (`ext_cr_detail.css`, beside `.crd-goalline`): one
`.cr .crd-hl-band` rule (pill: 1px border, 999px radius, 11px mono, `--text-muted`) + tints reusing
the existing state tokens: `.crd-hl-blocked` → the awaiting/amber tokens the state pill uses,
`.crd-hl-working` → working, `.crd-hl-done` neutral; a `done` band whose raw `state` is `failed`
adds `.crd-hl-failed` → `--surface-failed/--line-failed/--text-failed` (`:325-332`) and the pill text
"Completed · failed" (likewise " · stopped", untinted). Check light theme via the existing
`.cr` token set (no new tokens). Phone: `.crd-goalline` is NOT hidden ≤600px (only `.crd-statchips`
and `.crd-backline` are, `:1879, :2075`), so the line + pill show on phone/tablet unchanged.
`overview.goal` stays (classic Overview card `app.js:1979` and the CR summary panel still read it).
Restart required (page is baked at startup).

**A4b. Classic parity (F5).** Same server `headline`, no JS policy. `aitracker/web/index.html:181`
(the Overview card's Goal row): add, directly above it,
`<div class=ovrow id=ov_hlrow style=display:none><span class=ovk>Status</span><span id=ov_hl class=ovv></span></div>`.
`app.js` next to `:1979`:
`const hl=d.headline||{}; $("ov_hlrow").style.display=hl.text?"":"none"; $("ov_hl").innerHTML=(hl.label?'<span class="hlband hl-'+esc(hl.band||"")+'">'+esc(hl.label)+'</span> ':'')+md(hl.text||"");`
CSS in `app.css` (one `.hlband` pill rule + `.hl-blocked` amber / `.hl-working` / `.hl-done` tints
from the existing classic tokens `--amber`, `--green`, `--muted`). Phone/tablet: the Overview card is
already responsive; nothing extra.

**A5. What does NOT change:** `overview.now` (`claude.py:2065-2066` still writes the `⧖ question` for
live blocked jobs — that's the board tile/banner), `_blocked_jobs`, the list dict, the board.

---

### B. Cost calculator (C8, C9, C10)

**B1. One price table + one pricing function** — `aitracker/util.py`, directly after `model_label`
(`:514-535`), so both providers import it the way they already import `model_label`/`real_model`
(no new module → no `scripts/bundle.py` edit; names `PRICE_`/`cost_` prefixed for the flattened bundle).
```python
# $/MTok: (input, write_5m, write_1h, cache_read, output). Source: platform.claude.com/docs/en/
# about-claude/pricing, fetched 2026-11-13 — standard tier, global geo. Cache-read is NOT a fixed
# 0.1x (Opus/Sonnet 5.5 0.05x, Fable 5.1 0.025x), so every column is explicit.
PRICE_TABLE = {
    ("opus", (5, 5)): (4, 5, 8, 0.20, 20),
    ("opus", (5,)): (5, 6.25, 10, 0.50, 25),
    ("opus", (4, 8)): (5, 6.25, 10, 0.50, 25), ("opus", (4, 7)): (5, 6.25, 10, 0.50, 25),
    ("opus", (4, 6)): (5, 6.25, 10, 0.50, 25), ("opus", (4, 5)): (5, 6.25, 10, 0.50, 25),
    ("sonnet", (5, 5)): (2, 2.50, 4, 0.10, 10), ("sonnet", (5,)): (2, 2.50, 4, 0.20, 10),
    ("sonnet", (4, 6)): (3, 3.75, 6, 0.30, 15), ("sonnet", (4, 5)): (3, 3.75, 6, 0.30, 15),
    ("haiku", (5, 5)): (0.10, 0.125, 0.20, 0.01, 0.50),
    ("haiku", (4, 5)): (1, 1.25, 2, 0.10, 5),
    ("fable", (5, 1)): (10, 12.50, 20, 0.25, 50),
}
PRICE_HAIKU55_LONG = (0.50, 0.625, 1, 0.05, 2.50)   # a request whose prompt (in+reads+writes) > 100,000
PRICE_BASIS = "API list price, USD, standard tier — not your plan's bill"

def cost_usage(u):
    """(in, w5m, w1h, read, out) ints off one usage block; the 5m/1h breakdown wins when non-zero,
    else the top-level cache_creation figure is charged as 5m (seen on OpenRouter rows)."""

def cost_add(acc, model, u, speed=None):
    """Fold ONE request into acc = {model_id: [in, w5m, w1h, read, out, usd|None, n_long]}.
    Haiku 5.5 is priced per request by its prompt size, so the $ is accumulated here per request,
    not derived from the totals later. Unknown model or speed not in (None, "standard") -> usd None."""

def cost_summary(main_acc, agent_acc, agent_costs, note=None, reported=None, recorded=None):
    """The detail dict's `cost` (shape below). Savings = read_tokens*(input-read) per model;
    write_premium = w5m*(w5m_price-input) + w1h*(w1h_price-input); net = gross - premium.
    `agent_costs` = [(aid, label, usd|None)]. `reported` = Claude's last cost-state
    {"usd","unknown"} or None (F1). `recorded` = (main_usd, agents_usd) a provider BILLED (Auggie, F2):
    it overrides main_usd/agents_usd/total_usd and switches `basis`; savings stay list-price."""
```
- Price lookup helper `_price_for(model)`: `model_version(model)` → `PRICE_TABLE`; if that is None,
  retry once with a trailing context-size tag stripped, `re.sub(r"-\d+k$", "", model)` (F2:
  `claude-opus-4-7-500k` → opus 4.7). Used for **savings and the by-model breakdown only** when a
  provider passes `recorded`; a Claude transcript never has such ids, so it changes nothing there.
- `cost_add` keys by the **raw** `message.model` (so the breakdown can show it) and prices via
  `util.model_version()` (`:488`) → `PRICE_TABLE.get(mv)`; `real_model()` (`:480`) empty →
  skipped entirely (`<synthetic>` rows carry no billable tokens). OpenRouter ids (`vendor/model`),
  `claude-fable-…` versions not in the table, and any `speed:"fast"` row → `usd None` =
  **unpriced**, listed with token counts, never $0 (C8 "unknown model → flagged").
- `acc` values are plain lists of numbers → picklable (required: `_transcript_pass` output is pickled
  by `file_pass`).

**B2. Claude main transcript — same pass, no re-read** (`claude.py:_transcript_pass` `:1634`).
- Beside `seen_mid` (`:1677`): `cost_last = {}   # message.id -> (model, speed, usage): LAST line wins`.
- In the per-line block (`:1719`), independent of the existing first-seen gate (left untouched; the
  `tokens` count keeps first-seen — F10): `if u: cost_last[mid or ("_%d" % line_no)] = (msg.get("model"), u.get("speed"), u); cost_state = None`.
- **F1 — Claude Code's own exit figure.** Beside `cost_last`: `cost_state = None`. In the line loop,
  right after the `toolUseResult` handling (`:1713-1715`) and **before** the `msg` guard at
  `:1716-1718` (a `cost-state` line has no `message`):
  `if o.get("type") == "cost-state": cost_state = {"usd": o.get("totalCostUSD") if isinstance(o.get("totalCostUSD"), (int, float)) else None, "unknown": bool(o.get("hasUnknownModelCost"))}`.
  The `cost_state = None` in the usage branch above means only a cost-state written **after** the
  last usage line survives (i.e. it describes the whole transcript). Never summed — it is cumulative.
- After the loop: `cost_tok = {}; for m_, sp_, u_ in cost_last.values(): cost_add(cost_tok, m_, u_, sp_)`;
  add `"cost_state", "cost_tok"` to `_PASS_NAMES` (`:1627-1631`) and to the unpacking tuple in
  `parse_session` (`:1913-1916`) — keep both lists alphabetical (the comment at `:1624` says they were
  derived by an `ast` walk; `_PASS_NAMES` is picked from `locals()` at `:1908`, so the tuple order is
  what must match): insert `cost_state, cost_tok` after `commits`, before `ctx_current`.
- Memory: one tuple per message id per session (tens of thousands worst case), dropped after the pass;
  the pickled cache only stores `cost_tok` (a handful of models).

**B3. Background agents — same cached per-file pass** (`claude.py:_agent_file_pass` `:1131`).
- Same `cost_last` dict inside the file loop (where `_hb_agent_line` is called, `:1185`); after the
  loop `ctok = {}` via `cost_add`; return it on the entry as `"cost": ctok` (entry-level, next to
  `"hb"` — **not** a new public `agents_bg[]` row field; the review's cut: nothing renders it).
- `parse_agents()` (`:1304`): new optional out-param mirroring `hb`: `def parse_agents(path, hb=None, cost=None)`;
  in the merge loop (`:1325-1335`) `if cost is not None: _cost_merge(cost["tok"], e["cost"]);
  cost["per"].append((e["aid"], e["row"]["desc"], _acc_usd(e["cost"])))` (sum lists element-wise;
  `usd` stays None if either side is None; `_acc_usd(acc)` = sum of the priced `usd`s, None when
  none is priced — both 3-line helpers in `util.py` beside `cost_add`). Return tuple unchanged (5 callers incl. tests at
  `tests/test_selfcheck.py:138`, `tests/test_agent_cache.py:144`).
- `parse_session` (`:1955`): `agent_cost = {"tok": {}, "per": []}; … parse_agents(path, hb_ag, agent_cost)`;
  result dict (`:2042`) adds
  `"cost": cost_summary(cost_tok, agent_cost["tok"], agent_cost["per"], reported=cost_state),`.
- Scope of "agents": `agents_bg` = `<session-id>/**/agent-*.jsonl` (Task/Agent sub-agents and
  workflow agents). **Not** `agent_sessions` (separate SDK/worktree sessions, other transcripts) —
  pricing those means parsing other sessions per poll (the cost `registry.py:169-175` already refuses).
  The modal says so in one line.

**B4. Auggie — what Augment billed (F2)** (`aitracker/providers/auggie.py:590-598`, the existing
`for rn in ex.get("response_nodes") or []:` loop; same pass, no re-read):
- Tokens, as before: `cost_add(cost_tok, ex.get("model_id") or "", tu)` inside the existing
  `if isinstance(tu, dict):` branch (no message id → no dedupe needed).
- Billed $: in the same loop, a separate check (billing sits on a **different** node from
  `token_usage`, so the two never double count):
  `bm = rn.get("billing_metadata")` → `if isinstance(bm, dict):` `try: rec_usd += float(bm.get("cost_usd") or 0)`
  `except (TypeError, ValueError): pass` (a non-numeric string is skipped, never raised).
- Sub-agents: `sub = d.get("subAgentCostUsd")` (`d` = the session dict loaded at `auggie.py:527`);
  numeric → `agents_usd`, else 0.
- Result dict (`:769`):
  `"cost": cost_summary(cost_tok, {}, [], recorded=(rec_usd, sub_usd), note="Billed by Augment (about 1.3× Anthropic list price). Cache savings are at Anthropic list price.")`.
  With `recorded`, `basis` = `"Billed by Augment, USD"`; `main_usd`/`agents_usd`/`total_usd` come
  from `recorded`; the by-model breakdown and cache savings use `_price_for` with the `-500k` alias.
- Unreadable stub (`_degraded_auggie_detail`, `auggie.py:478-523`): no `cost` key → the seam default.
Augment VS Code ext (`augment_ext.py:287`) has no usage → covered by the seam default below.
Seam (`registry.py`, beside A3): `d.setdefault("cost", cost_summary({}, {}, [], note="No per-turn usage recorded for this source."))`.
F6 note, same place, after the setdefault (server-owned text; no parent re-parse):
`if d.get("continued_from"): d["cost"]["note"] = ((d["cost"].get("note") or "") + " Includes history copied from the session it continues.").strip()`
(`continued_from` is set a few lines earlier, `registry.py:177`).

**B5. `cost` JSON shape (exact):**
```json
"cost": {
  "basis": "API list price, USD, standard tier — not your plan's bill" | "Billed by Augment, USD",
  "total_usd": 12.34,            // main_usd + agents_usd (priced part only); null if nothing priced
  "main_usd": 9.10, "agents_usd": 3.24,
  "reported_usd": 12.20 | null,  // Claude only: last cost-state after the last usage line (F1)
  "reported_unknown": false,     // its hasUnknownModelCost
  "cache": {"read_tokens": 41000000, "saved_gross_usd": 160.2,
            "write_premium_usd": 21.7, "saved_net_usd": 138.5},
  "models": [ {"model": "claude-opus-5-5", "label": "Opus 5.5", "who": "main"|"agents",
               "usd": 9.10|null, "in": 1200, "w5m": 0, "w1h": 900000, "read": 38000000,
               "out": 210000, "long": 0} ],          // sorted by usd desc, unpriced last
  "agents": [ {"aid": "...", "label": "<agents_bg desc>", "usd": 1.2|null} ],   // top 10 by usd
  "unpriced": [ {"model": "openai/gpt-6-luna", "tokens": 1234567} ],
  "note": null | "..."
}
```
`label` via `util.model_label()`. All `usd` rounded to 4 dp server-side; formatting to `$12.34` is
the client's job (rendering, not policy).

**B6. Render — one chip, one modal opener, both views.**
- `app.js`, top level next to `openText` (`:2226`): `function costChipText(c)` → `"$" + total.toFixed(2)`
  (+ `"+?"` when `c.unpriced.length`), `"unpriced"` when only unpriced, `""` when no usage (chip
  hidden); and `function openCostModal(c)` → builds markdown and calls
  `openText("Cost", c.basis, md)` — the existing `#msgmodal` shell (`index.html:237`), which
  `mdBlock` renders with its table support (`app.js:198-204`). Content: a 4-row summary table
  (Burned total · Main session · Agents · Saved by caching (net) — with gross and write premium in
  the cell), then "Agents" table (label, $) when any, then "By model" table (model, who, $, in, cache
  writes, cache reads, out), then `**Unpriced:**` list, then — when `c.reported_usd != null` — one
  line "Claude Code reported $X at last exit (includes sub-agents)" (+ " — some models unpriced by
  Claude Code" when `reported_unknown`) (F1), then `c.note` (which carries the F2 billing note and
  the F6 "copied history" note), then the one-line agent_sessions caveat.
  `window.openCostModal = openCostModal`.
- Classic (`app.js:1887-1891`): append
  `+(costChipText(d.cost)?`<span class="chip clk" onclick="openCostModal(lastData.cost)" title="Cost breakdown"><span class=lbl>cost</span><b>${esc(costChipText(d.cost))}</b></span>`:"")`
  (`lastData` is the module's current detail dict, used by `copyNote` `app.js:2449`).
- Control Room (`ext_cr_detail.js` `statChipsHtml` `:1058-1066`): add after the tokens chip a
  **button** variant — extend `statChip(label, value, opts)` (`:1021`) with `opts.act`: when set,
  render `<button type="button" class="crd-statchip crd-statchip-cost mono" data-act="cost" …>`
  (same inner spans, so it looks identical; a real button = keyboard + touch). Delegated handler
  (`:1773` switch): `case "cost": if (typeof openCostModal === "function") openCostModal((ui.lastSession || {}).cost || {}); break;`
  — `ui.lastSession` is how sibling cases reach the session (`:2009`).
- Phone: `.cr .crd-statchips { display:none }` (`ext_cr_detail.css:1879`) would hide the cost chip
  on phone. Change that one rule to
  `.cr .crd-statchips > .crd-statchip:not(.crd-statchip-cost) { display: none; }` so the row shows
  only the cost chip ≤600px; add `.cr .crd-statchip-cost { cursor:pointer; min-height:44px }` inside
  the same media block (the 44px hit-target rule the block already applies, `:1880-1886`). Tablet
  (601–900px) already shows the whole row. `#msgmodal` is the shared overlay already used on phone.
- No host gating anywhere (read-only data; tracker-gap rule).

---

### C. Draft-reply copy button (C11)

**C1. Detection — one predicate, the smallest rule that covers all 7 real drafts and none of the 6
false labels:** a **blockquote run** (consecutive lines matching `/^\s*>/`) whose nearest preceding
non-blank line is a **label line** — it starts with `**…**` or `#…` — and that label's text matches
`/\bdraft\b/i`. Requiring the blockquote is what excludes "**Draft plan:**" + list, "…stays
draft.**" + paragraph, "## 4. …saved draft task…" + mermaid, and prose mentions. (`suggested
reply` labels: 0 found on disk → not added.)

**C2. Renderer — `mdBlock()` only** (`aitracker/web/app.js:172-216`), the one block renderer every
narration surface already reaches:
- New blockquote branch, before the paragraph branch (`:217`):
  ```js
  if(/^\s*>/.test(l)){ const start=i, q=[]; while(i<L.length&&/^\s*>/.test(L[i])){ q.push(L[i].replace(/^\s*>\s?/,"")); i++; }
    const raw=q.join("\n"), inner=mdBlock(raw);
    out.push(draftLabelBefore(L, start)   // nearest non-blank line above `start` is a draft label
      ? `<div class="cblock dq"><button class=codecopy onclick="copyCode(this)" title="Copy this draft">${ico('copy')} Copy</button><textarea class=cpsrc hidden readonly>${esc(raw)}</textarea><blockquote class=mdq>${inner}</blockquote></div>`
      : `<blockquote class=mdq>${inner}</blockquote>`); continue; }
  ```
  The label test looks back over `L` from the quote's first line to the previous non-blank line
  (`draftLabel(line)` = `/^\s*(\*\*[^*\n]*\*\*|#{1,6}\s)/.test(line) && /\bdraft\b/i.test(labelText)`
  where labelText is the bold span or heading text) — a pure function of the source lines, so the
  label's own paragraph still renders normally just above. `window.hasDraftQuote(s)` exports the same
  predicate over a whole string (used in C3).
- Paragraph loop guard (`:218`): add `&&!/^\s*>/.test(L[i])` so a label paragraph stops at the quote
  (this is the actual "> rendered inline" fix, and applies to all 62 blockquotes — they now render as
  real quotes instead of `&gt; text` paragraphs; a strict improvement, called out in the PR).
- Copy semantics: `copyCode` (`:2346`) gets a 2-line preference: `const src=btn.parentNode.querySelector(".cpsrc");`
  if present, text = `src.value`, and the non-secure-context fallback (LAN/tunnel http — no
  `navigator.clipboard`) temporarily un-hides the textarea, `select()`s it and runs
  `execCommand("copy")` — the same textarea technique `copyNote` already uses (`app.js:2454-2455`) —
  because `fallbackCopy()`'s Range selection can't select a `hidden` element. Same button, same
  `.codecopy` CSS (`app.css:396-398`, CR `ext_cr_detail.css:1524-1528`), same "✓ Copied" feedback.
  Fences keep the `<code>` path untouched → exactly one button per fence, one per draft quote.
- Copied text = the quote's **raw markdown with only the leading `> ` (or `>`) stripped per line**;
  the label line is not part of it (it's outside the quote). Inline `**bold**`, `` `code` ``,
  `*italic*`, links and emoji shortcodes are kept verbatim. Justification: the drafts on disk are
  already written in their target's syntax — the Slack one uses Slack-native `*bold*` and `:mag:`,
  the Jira one `**Summary:**` — and Slack's composer renders pasted `` ` ``/`*`/`**` markup, so any
  transformation (stripping or converting) would lose information the author put there on purpose.
  (Decision D5 if the user wants plain text instead.)
- CSS: `.mdq` (both `app.css` and CR's `.cr` scope beside `.cr .cblock` `ext_cr_detail.css:1509`):
  left border 3px `var(--line3)`/CR `--line-subtle`, padding-left 10px, muted text; `.cblock.dq`
  reuses `.cblock`'s `position:relative` so the button sits top-right as on code; `.cblock.dq .mdq`
  gets `padding-right: 72px` so the button never covers text on a narrow phone.
- **Fence inside a draft quote (F8 — test only, no extra code).** `> ```…` recurses into an inner
  `.cblock` with its own Copy button. The two cannot collide: the inner `.cblock` sits inside
  `.mdq`, whose `padding-right: 72px` keeps the inner button 72px left of the outer one; and the
  inner button's `parentNode` is the inner `.cblock`, which contains no `.cpsrc`, so it copies only
  its code while the outer copies the whole draft (fence lines included). No `:scope` selector and
  no extra CSS needed; the test in §E pins both.

**C3. Every surface that renders narration:**
- Narration modal / prompt / task modals → `openText` → `mdBlock` (`app.js:2226-2233`) — covered.
- CR timeline entries & panels → `mdHtml(ctx, text)` (`ext_cr_detail.js:198-224`) routes to `mdBlock`
  only when the text has a fence; extend the condition to
  `(text.indexOf("```") !== -1 || (typeof hasDraftQuote === "function" && hasDraftQuote(text)))`.
  Clicking a CR entry already opens the same modal (`openTimelineEntry` `:3581`). Known gap (F9, no
  change, same as base — say so in the commit message): a plain non-draft `>` quote in a CR
  timeline entry still renders inline as `&gt; …` there, while the modal shows a real blockquote.
- Classic narration list row (`app.js:2022`) is a one-line clamp on inline `md()` that opens the modal
  on click — **no button in the clamp** (a button inside a click-to-open row would fight it); the
  modal it opens has the button.
- Auggie: same `narrative[]` → same renderers → inherited, no Auggie code.

---

### D. Sequencing (each step leaves `make check` green; commit per step in the worktree)

1. **util pricing** (B1) + its unit tests — pure, no consumers yet.
2. **Claude cost** (B2 incl. F1 `cost_state`, B3) + **Auggie billed cost** (B4, F2) + seam default
   + F6 note + tests. Server-only; restart shows `cost` in `/api/session`.
3. **config HEADER_LINE** (A1 Python part) + **job reader** with the F3 live gate (A2) + **seam
   headline** (A3) + tests.
4. **CR + classic render**: header line (A4) + classic `ov_hl` row (A4b, F5), cost chip + modal
   with the F1 "reported" line (B6), Config row (A1 JS) + node tests.
5. **C11** mdBlock blockquote/draft branch + copyCode `.cpsrc` + mdHtml routing + CSS + node tests
   (incl. the F8 nested-fence test).
6. `make check` (prefix `unset TRACKER_AUTH;`, one module per process if OOM — see memory), restart,
   curl proofs (Step 4.5 of /tracker-gap) for one job session, one non-job Claude session, one Auggie
   session; phone (375px) + tablet (768px) check of the header line, the cost chip and a draft quote.
Server steps first because the client reads keys that must already exist; C11 last because it is
client-only and independent (can be a separate commit on the same branch/PR — rule 9).

### E. Tests (new files; node-based ones follow `tests/test_classic_markdown_and_links.py:54-90`'s
"run the real app.js under node with stubs", `skipUnless(_HAS_NODE)`)

`tests/test_session_cost.py` (pure Python):
- `test_price_table_matches_cli_cost_state` (F1; replaces the tautological table-vs-itself test) —
  fixture rows copied from real `cost-state.modelUsage` records, priced through `cost_add` and
  compared to Claude Code's own `costUSD` within 1e-6: opus-5-5 {in 4,465, out 321,099, read
  74,318,753, w1h 1,305,144} → 31.7447426; sonnet-5-5 {in 462, out 104,141, read 38,375,246, w1h
  608,536} → 7.3140026; opus-5-5 {in 1,598, out 45,779, read 6,517,904, w1h 226,002} → 4.0335688
  (re-derived for revision 2). Red if any of those cells changes.
- `test_cost_state_reported_only_when_after_last_usage` (F1) — a transcript ending in a
  `cost-state` line → `cost.reported_usd == totalCostUSD`, `reported_unknown` mirrors
  `hasUnknownModelCost`; append one more usage line → `reported_usd is None`; two cost-state lines →
  only the last is used (not summed).
- `test_cost_last_usage_per_message_id_wins` — 3 lines same `message.id`, output 1→120→287: cost uses
  287; a 4th id-less line still counts; existing `tokens.out` is unchanged (first-seen kept, F10).
- `test_cache_creation_breakdown_wins_and_top_level_fallback` — `{cc_input:0, cc:{1h:9780}}` charged
  as 1h; `{cc_input:500, cc:{0,0}}` charged as 5m.
- `test_cache_savings_gross_premium_net` — hand-computed numbers for opus 5.5 (read 0.20 vs input 4).
- `test_haiku55_long_prompt_tier_per_request` — one request at 99,999 prompt tokens and one at 100,001
  priced at different rows.
- `test_unknown_and_openrouter_models_flagged_unpriced` — `claude-fable-9-9`, `openai/gpt-6-luna`,
  `speed:"fast"` → `usd null`, listed in `unpriced`, `total_usd` excludes them, never 0-for-unknown.
- `test_synthetic_model_skipped`.
- `test_agents_cost_split_and_rows` — temp project dir with a main jsonl + `<sid>/subagents/agent-x.jsonl`
  (fixture style of `tests/test_agent_cache.py`): `main_usd`, `agents_usd`, `agents[0].usd`; no
  `cost_usd` key on `agents_bg[]` rows; second call hits the agent cache and returns the identical `cost`.
- `test_auggie_recorded_cost_and_subagents` (F2; replaces `test_auggie_cost_unpriced_with_note`) —
  temp `~/.augment/sessions` (fixture style of `tests/test_auggie_drilldown.py`), one exchange with
  node A `{token_usage:{…}}` + node B `{billing_metadata:{cost_usd:"1.832267125"}}`, session
  `subAgentCostUsd: 1.72737669`, `model_id: claude-opus-4-7-500k` → `main_usd 1.8323`, `agents_usd
  1.7274`, `total_usd 3.5596`, `basis == "Billed by Augment, USD"`, `cache.saved_gross_usd > 0`
  (via the `-500k` alias), token counts present. Red under revision 1 (null).
- `test_auggie_bad_cost_string_skipped` (F2 negative) — `cost_usd: "n/a"` and a missing
  `subAgentCostUsd` → no exception, that node contributes 0.
- `test_seam_default_cost_for_providers_without_usage` — augment_ext detail via `parse_any` has `cost`
  with `total_usd null` and a note.
- `test_continued_session_cost_note` (F6) — `config.FORKS_FILE` repointed to a temp forks.json
  linking child→parent → the child's `parse_any` detail has `cost.note` containing "copied"; the
  parent's doesn't.

`tests/test_job_headline.py` (pure Python; fixture style of `tests/test_jobs_waiting.py:20-60`, which
repoints `config.JOBS_DIR`/`config.PROJECTS`):
- `test_default_mode_is_summary` — `config.resolve_header_line({}) == "summary"`; `config.HEADER_LINE`
  default; `"HEADER_LINE" in config.EDITABLE`, not in `RESTART_REQUIRED`; validator rejects `"prompt"`.
- `test_summary_from_job_detail_direct_dir` — job dir `sid[:8]` with `detail` → `headline.source=="job"`,
  text == detail, label per band.
- `test_job_found_via_resume_session_id` — dir named after `sessionId[:8]`, transcript named
  `resumeSessionId` → found.
- `test_prefix_collision_not_borrowed` — dir `sid[:8]` whose `state.json` lists a different full id → `job is None`.
- `test_band_mapping_each_state` — one case per row of the §0 mapping table: done/failed/stopped +
  idle → Completed (failed/stopped keep raw `state`), done + `tempo:"active"` → Working, any state +
  `tempo:"blocked"` → Needs input, blocked + `tempo:"idle"` → Working; `"review"` never emitted
  (job dir in the stubbed live set for every case, so F3's gate doesn't interfere).
- `test_dead_blocked_job_keeps_text_drops_pill` (F3) — empty roster (synthetic, as
  `tests/test_jobs_waiting.py:_write_roster` does) + a blocked/`tempo:blocked` job →
  `headline.text == detail`, `label is None`, `band is None`, `job.state == "blocked"`; same job with
  its short in the roster → "Needs input"; a dead `done` job still → "Completed". Red under revision 1.
- `test_missing_job_file_falls_back_to_narration` — no job dir; and a dir with only `tmp/`.
- `test_malformed_state_json_falls_back` — invalid JSON, a JSON list, `detail: 42` → no crash, narration.
- `test_empty_detail_uses_needs_then_result`.
- `test_narration_mode_ignores_job` — `HEADER_LINE="narration"` + a job → newest narration text.
- `test_auggie_headline_is_narration` — Auggie session → `job None`, `source "narration"`.
- `test_no_narration_source_none` — empty session → `source "none"`, `text ""`.
- `test_config_post_roundtrip` — POST `/api/config {"key":"HEADER_LINE","value":"narration"}` on an
  ephemeral server (pattern of `tests/test_cr_routes.py:262+`) → next `/api/session` headline mode flips
  without restart; bad value → 400.

`tests/test_header_and_cost_ui.py` (node):
- `test_cr_header_line_renders_headline_text_and_band_pill` — real `renderHeader` with a session whose
  `headline` has label "Needs input": `.crd-goalline` contains the pill + text; with `label:null` no pill;
  with `text:""` the line is hidden.
- `test_cr_cost_chip_is_button_and_opens_modal` — `statChipsHtml` emits `data-act="cost"` button with
  `$12.34+?`; no `cost`/no usage → no chip; dispatching the click calls `openText("Cost", …)` with the
  summary table.
- `test_classic_cost_chip_present` (bundle-string assertion like `test_classic_markdown_and_links.py:99+`).
- `test_classic_overview_renders_headline` (F5) — real classic `render(d)` under node with a
  headline labelled "Needs input" → `#ov_hl` holds the pill + text and `#ov_hlrow` is shown;
  `text:""` → `#ov_hlrow` hidden. Red before A4b.
- `test_cost_modal_reported_line` (F1) — `openCostModal({…, reported_usd: 12.2})` passes markdown
  containing "Claude Code reported $12.20 at last exit"; `reported_usd: null` → no such line.
- `test_phone_css_keeps_only_cost_chip` — the ≤600px block hides `.crd-statchip:not(.crd-statchip-cost)`
  and no longer hides `.crd-statchips` wholesale.
- `test_config_dialog_has_header_line_row` — `serverRow('Header line', 'HEADER_LINE'` in the bundle.

`tests/test_draft_copy.py` (node, real `mdBlock`/`copyCode`):
- `test_bharadwaj_shape_gets_one_copy_button` — the exact real text (label line + `>` lines) → one
  `.cblock.dq` with one `.codecopy`, `.cpsrc` value == the quote without `> `, label paragraph rendered
  above, no literal `&gt;` in the output.
- `test_heading_label_then_blank_then_quote` — "## 3. Slack message draft …\n\n> *AIO…* :mag:" → button;
  copied text keeps `*…*` and `:mag:` verbatim.
- `test_negatives_no_button` — "**Draft plan:**\n1. …" (list), "the PR stays draft" prose + a `>` quote
  not preceded by a draft label, "## 4. … draft task …\n```mermaid…" → zero `.dq`.
- `test_plain_blockquote_renders_as_blockquote_without_button`.
- `test_code_fence_keeps_single_button_inside_draft_doc` — a draft quote plus a fence in one text →
  exactly 2 `.codecopy` total (1 each); a fence alone → 1.
- `test_fence_inside_draft_quote` (F8) — "**Draft reply**\n> text\n> ```\n> code\n> ```" → exactly
  2 `.codecopy`; the outer button's `.cpsrc` value contains the fence lines; clicking the inner
  button copies only `code`; the inner `.cblock` is a descendant of `.mdq` (so the 72px
  padding-right keeps the buttons apart).
- `test_copycode_uses_cpsrc_and_textarea_fallback` — stub `navigator.clipboard` undefined and a fake
  `document.execCommand`; `copyCode(btn)` copies `.cpsrc.value`, button shows "Copied".
- `test_cr_mdhtml_routes_draft_text_to_mdblock` — `hasDraftQuote` true → `mdHtml` output has `.dq`.

Self-check / evals (tracker-gap Step 4.1): one assertion each in `tests/test_selfcheck.py` — the Claude
fixture session's detail has `cost.total_usd > 0` and `headline.mode == "summary"`; the Auggie fixture
has `cost.total_usd > 0` (its recorded `billing_metadata` $, F2 — the fixture gains one billing node)
and a `headline` (both providers). Integration (`tests/test_integration.py`): boot the
server, `GET /api/session` for a temp job session → `headline.source == "job"` and `cost` present;
`GET /` page contains `data-act="cost"`-producing code and `hasDraftQuote`, and no
`location.hostname` gate on either. **Red-first proof:** for the dedupe test, revert B2's "last wins"
to first-seen and watch `test_cost_last_usage_per_message_id_wins` fail; for C11, drop the paragraph
guard and watch the Bharadwaj test fail.

### F. Risky spots and fallbacks

1. **Job → transcript mapping** (resume ids, 8-char collisions, stale working/blocked states). Fallback
   built in: full-id match required; any read error → narration; a non-`done` band of a job whose
   worker isn't live loses its pill (F3), the text stays.
2. **Price drift.** Prices are a code constant with a fetched-on date; a new model id (e.g. Opus 5.6)
   shows as **unpriced**, never wrong-priced. Fallback: add a row. The chip says "+?" so a partial
   total is never mistaken for a full one. Pinned against Claude Code's own `costUSD` for opus-5-5 /
   sonnet-5-5 (F1); haiku-5-5, haiku-4-5, opus 4.x and fable 5.1 have no new-format record to check
   against and keep their fetched-on date (F11).
2b. **Recompute vs Claude Code's exit figure diverge on some sessions** (`4405110a`, `7d44ec42`; not
   explained). Not hidden: the modal shows both when a trailing `cost-state` exists (F1). Known gap.
2c. **Forked/continued sessions include copied parent history** (F6) — stated in `cost.note`; no
   parent re-parse.
3. **Pickled pass cache shape change.** Adding `cost_state`/`cost_tok` to `_PASS_NAMES` changes the cached blob's
   keys; the cache is in-process (`util.py:539`) so a restart clears it — no migration. The agent cache
   (`_AGENT_CACHE`) likewise. Both kill-switches still work (`AITRACKER_NO_AGENT_CACHE`, `_pass_cache_on`).
4. **Per-poll job scan cost** for non-job sessions (listdir + ~111 stats + small unpickles), with
   per-file `file_pass` caching. Accepted as is — no memo (F7: a JOBS_DIR-mtime memo would miss resumes).
5. **mdBlock blockquote branch changes 62 existing quote renders.** Recursion on `raw` is bounded by
   the quote's own lines (each level strips one `>`), so no runaway. Fallback if a regression shows:
   render non-draft quotes exactly as before (keep the paragraph guard only for the draft case).
6. **Phone chip row.** Only the cost chip survives ≤600px; if it crowds the phone header, move it into
   `.crd-phonehead` instead (same button, same handler).

### G. Decisions the user may want to overrule

- **D0 — no "Ready for review" group.** The CLI derives it from live GitHub PR check status of the
  job's child PRs; the tracker makes no outbound calls, so those jobs show as Working/Completed.
  Alternative: approximate it from the `prs[]` state the tracker already scrapes from the logs
  (merged/closed only — no check status), which would be a guess, so not proposed.
- **D1 — two options only, as asked (review F4 rejected by the orchestrator).** `HEADER_LINE` ∈
  {summary (default), narration}; non-job sessions fall back to narration, so the last-prompt line
  leaves the CR header for every non-job session (Auggie and augment_ext included — augment_ext's
  narration is a "transcript can't be read" system note plus synthetic file-touch entries,
  `augment_ext.py:254-261`, so its header shows one of those). The prompt stays
  in the classic Overview card and the timeline. Worth one confirming sentence to the user.
- **D2 — "burned in this session" = main transcript + its background agents.** Claude: a live
  recompute at **API list price** (`basis` says so — under a Max/Team/Enterprise plan this is an
  equivalent, not the bill), with Claude Code's own exit figure shown beside it when one exists
  (F1). Auggie: **what Augment billed** (≈1.3× list), labelled as billed (F2). Separate agent
  *sessions* (`agent_sessions`) are excluded.
- **D5 (C11) — copy keeps the draft's markdown verbatim** (only `> ` stripped). Alternative: copy
  plain text (strip `**`/`` ` ``/`*`), better for email, worse for Slack/Jira.
- **D6 (C11) — copy button only on draft-labelled quotes**, not on every blockquote (62 others are
  quoted prompts/specs). Alternative: a button on every blockquote — removes the label heuristic.

## Review

Author: opus adversarial reviewer, 2026-11-13. Every cited symbol was re-grepped at `251a98a`;
real-data claims were re-run read-only against `~/.claude/jobs` (111 state.json),
`~/.claude/projects` (400 newest transcripts + their `agent-*.jsonl`) and `~/.augment/sessions` (88).

**Verified as the plan states (no finding):** HEADER_LINE wiring. `EDITABLE` `config.py:207`,
`VALIDATORS`/`_v_enum` `:236,:251`, `_RESOLVERS` `:502`, `_PLAIN_ATTR_KEYS` `:523`,
`apply_overrides` `:543` (called at `server.py:421,616,918`). Policy stays on the server, and the
setting is live after a POST. The one caveat is shared with GATEWAY: a hand-edited config.json only
lands on the next GET/POST `/api/config`. `_PASS_NAMES` is picked from `locals()`
(`claude.py:1908`), so adding `cost_tok` works if the unpack tuple at `:1913-1916` stays in the
same order. `narrative` is newest-first in Claude and Auggie (`claude.py:2040`, `auggie.py:767`).
Band mapping matches the CLI's `Is()`. Agent files never share a `message.id` with their main
transcript (0 of 2,082 files) or with each other, so main + agents does not double count.
**Price table checked against Claude Code's own `costUSD`** (see F1): opus-5-5, sonnet-5-5 and
sonnet-5 recompute at a ratio of exactly 1.000 (45/28/1 records). util.model_version handles
`claude-haiku-4-5-20251001` → (4,5) and `[1m]` suffixes, but returns `None` for
`claude-opus-4-7-500k` (relevant to F2).

### Findings

| # | Sev | Defect (file:line) | Repro (input → actual vs expected) | Fix direction (and what must NOT change) | The way | Test (red before fix) |
|---|---|---|---|---|---|---|
| F1 | **High** | The plan never mentions that Claude Code already writes its own cost into the transcript: `{"type":"cost-state","totalCostUSD",…,"modelUsage":{<model>:{inputTokens,outputTokens,cacheReadInputTokens,cacheCreationEphemeral5mInputTokens,cacheCreationEphemeral1hInputTokens,costUSD}},"hasUnknownModelCost"}`. It is in 111 of the 400 newest transcripts, written at process exit (100 at EOF, 11 mid-file = resumed), and its total **includes sub-agents**. The plan's only price test (`test_price_table_rows_match_pricing_page`, §E) compares the table to a copy of itself, so it is tautological. Breaks conventions rule 7. | Session `4405110a`: CLI says $106.86, the plan's recompute gives $3.87 (no agent files). `7d44ec42`: CLI $12.20, recompute $61.53. Over 49 new-format sessions, main+agents is within 2% of the CLI total in only 11; most land 2–10% under. A wrong price-table cell passes the plan's tests today. | **Keep** the live recompute: a live session has no fresh cost-state, because it is written at exit. **Add** (a) a price test against the CLI's own numbers and (b) one "Claude Code reported $X at last exit" row in the modal, shown only when the last `cost-state` comes after the last usage line. Do NOT replace the recompute with cost-state, and do NOT sum several cost-state lines (they are cumulative). | `_transcript_pass` (`claude.py:1634`): in the existing per-line loop, `if o.get("type")=="cost-state": cost_state={"usd":o.get("totalCostUSD"),"unknown":bool(o.get("hasUnknownModelCost"))}`. Any later usage line sets `cost_state=None`. Add `cost_state` to `_PASS_NAMES` and the unpack tuple (alphabetical, after `commits`/`cost_tok`). Pass it to `cost_summary(…, reported=cost_state)` as `cost.reported_usd`. One line in `openCostModal`. Auggie: `None` (seam default). | `test_price_table_matches_cli_cost_state`: fixture copied from the real modelUsage record. opus-5-5 {in 4465, out 321099, read 74318753, w1h 1305144} must give costUSD 31.7447426; sonnet-5-5 {462, 104141, 38375246, w1h 608536} must give 7.3140026; both via `cost_add` within 1e-6. Red if any cell changes. Second test: `cost-state` as the last line → `reported_usd` set; a usage line after it → `None`. |
| F2 | **High** | B4/D3 say Auggie is "unpriced" and has no agent cost. Wrong: **every** Auggie exchange (3,714/3,714) carries `response_nodes[].billing_metadata.cost_usd` (a *string*). It sits on a different response node from `token_usage`. Each session also has top-level `subAgentCostUsd` (88/88; non-zero e.g. 32.646633825). `auggie.py:591-598` reads only `token_usage`. | Real Auggie session → plan: `total_usd null`, every row "unpriced", agents $0. Expected: the recorded $ (e.g. one session sums to $239.30) and agents = `subAgentCostUsd`. Recorded/list-price ratio for opus-4-7 is exactly 1.300 over n=3,681 exchanges (min=max). So the recorded $ is Augment's price, 1.3× the Anthropic list price. | Auggie `main_usd` = sum of `float(billing_metadata.cost_usd)` over all response nodes. `agents_usd` = `subAgentCostUsd`. Keep summing tokens from `token_usage` for the breakdown and cache savings. Price those savings by aliasing `claude-opus-4-7-500k` → `("opus",(4,7))` **for savings only**, and say so in the note. Must NOT double-count: billing and usage nodes are separate entries in the same exchange. A non-numeric `cost_usd` is skipped, never raised. | In the `auggie.py:591` loop: `bm=rn.get("billing_metadata"); if isinstance(bm,dict): try: rec_usd+=float(bm.get("cost_usd") or 0) except (TypeError,ValueError): pass`. Give `cost_summary` an optional `recorded=(rec_usd, sub_usd)` that overrides `main_usd`/`agents_usd`; basis text "Augment-recorded USD". Alias in `cost_add`'s model→price lookup: `util.model_version(re.sub(r"-\d+k$","",m))`. Unreadable stub (`:508`) keeps the null cost. | `test_auggie_recorded_cost_and_subagents`: one exchange with node A `{token_usage:{…}}` + node B `{billing_metadata:{cost_usd:"1.832267125"}}`, plus `subAgentCostUsd: 1.72737669` → `main_usd 1.8323`, `agents_usd 1.7274`, `total_usd 3.5596`, `cache.saved_*` > 0. Red under the plan (null). Negative: `cost_usd: "n/a"` → skipped, no throw. Replaces `test_auggie_cost_unpriced_with_note`. |
| F3 | Medium | Stale jobs show as live. 51/111 state.json are `blocked/tempo:blocked`, many months dead (e.g. `99fd239f`, updatedAt 2026-08-08). A2 deliberately skips the live-roster gate, so the header shows a "Needs input" pill. The same header's `waiting`/state pill **is** live-gated (`_blocked_jobs` `claude.py:720`, used at `:1999,:2017`). Two pills in one header disagree (anti-drift). | Dead blocked job → band pill "Needs input", while `waiting=false` and the state pill says idle/ended. Expected: no claim that the job is waiting on input right now. | Keep the job's `detail` text (it is still the right summary). Drop the band label when the worker is not live and the band is not `done`. `done` stays labelled forever. Must NOT touch `_blocked_jobs` or `overview.now`. | `parse_session`: `live=_live_daemon_shorts()` once, then `job_for(sid, live)`. In `job_for`, after `_job_band`: `if band!="done" and short not in live: label=None; band=None` (keep `state`). | `test_dead_blocked_job_keeps_text_drops_pill`: empty roster + blocked/blocked job → `headline.text==detail`, `label is None`. Stub `_live_daemon_shorts` → {short} gives "Needs input". Red under the plan. |
| F4 | Medium | C2/D1 reading. Today's line is the last **prompt** (`overview.goal` = `requests[-1]`, `overview.py:19`). The user calls the choices "the last narration message or this kind of summary" while pointing at that prompt line. Under the plan's default (`summary` → narration fallback), **every non-job session** loses the prompt line: all Auggie and augment_ext sessions, and most Claude ones (only 111 sessions machine-wide are jobs). augment_ext's only narration entry is the explanatory NOTE (`augment_ext.py:256-261`), so its header would show that note. | Ordinary Claude session, default config → header shows the newest assistant narration where it used to show the user's last prompt. augment_ext → the "what isn't recorded" note. | Do not guess; this is the one decision to put to the user first. The cheapest fix that satisfies either reading: enum `("summary","narration","prompt")`, default `summary`. `summary` falls back to **narration** (as asked); `prompt` reproduces today's line. Must NOT change `overview.goal`. | `_v_enum(("summary","narration","prompt"))`, same tuple in `resolve_header_line`. In `headline()`: `if mode=="prompt": return {... "source":"prompt","text":(d.get("overview") or {}).get("goal") or ""}`. Third segment in the Config row. | `test_prompt_mode_shows_last_prompt` (Claude + Auggie fixtures) → `text == overview.goal`. Validator accepts "prompt", rejects "x". |
| F5 | Medium | Parity. A4 renders `headline` only in the Control Room. Classic gets the cost chip but no job summary. The owner's ruling recorded in `tests/test_view_parity.py:1-4` says "the session markers/pinned and other pieces of information must be same in both the UIs". | Classic view of a blocked job session: no summary and no band anywhere. CR shows both. | Render the same server `headline` in classic. No new policy in JS. | `app.js` Overview card (`:1979`, next to `ov_goal`): add an `ov_hl` row in `index.html` and fill it with `(h.label?'<span class="hlband hl-'+esc(h.band)+'">'+esc(h.label)+'</span> ':'')+md(h.text)`. Hide the row when `!h.text`. | Node test: classic `render(d)` with a headline labelled "Needs input" → `#ov_hl` holds the pill and the text; `text:""` → hidden. Red before. |
| F6 | Medium | Forked or continued transcripts copy their parent's history. 1,493 of 14,976 usage `message.id`s appear in more than one main transcript (e.g. `eed23597`/`b81bda8c` share 330). B2 counts every one of them as "burned in this session". | Forked session → its $ includes all of the parent's spend; adding up across sessions double counts. | Known gap: do **not** re-parse the parent on every poll to subtract it (registry `:169-175` already refuses that cost). State it in the modal. | `registry.parse_any`, after the cost setdefault: `if d.get("continued_from"): d["cost"]["note"]=(d["cost"].get("note") or "")+" Includes history copied from the session it continues."` (server-owned text). | `test_continued_session_cost_note`: forks.json links child→parent → `cost.note` contains "copied". |
| F7 | Low | The A2/F4 "memo on JOBS_DIR `st_mtime_ns`" fallback is wrong. A resume adds `resumeSessionId` by rewriting `<short>/state.json`, which bumps `<short>`'s mtime, not JOBS_DIR's, so the memo would miss newly-resumed jobs. The per-poll scan itself (≈146 entries, 111 stat+unpickle) is fine for now. | Memo built → job resumed → resumed transcript finds no job until a new job dir is created. | Keep the plain scan (the plan's default). **Delete** the memo fallback from the plan, or key it on the max mtime of the `<short>` dirs. Not built now. | Text change in A2 and §F.4 only. | None needed (nothing built). |
| F8 | Low | C11: a fence *inside* a draft quote (`> ```…`) recurses into an inner `.cblock` with its own Copy button, nested inside `.cblock.dq`. Both buttons sit top-right and can overlap. The plan's tests only cover a fence *next to* a quote. | `**Draft…**\n> text\n> ```\n> code\n> ```` → two stacked buttons. | Allowed (outer copies the whole draft, inner copies the code), but it must be tested and the buttons kept apart. Must NOT drop the inner button. | CSS `.cblock.dq .cblock .codecopy{top:auto;bottom:4px}`. `copyCode` reads `btn.parentNode.querySelector(":scope > .cpsrc")`, so an inner button never takes the outer textarea. | `test_fence_inside_draft_quote`: exactly 2 `.codecopy`. The outer copies raw text that includes the fence lines; the inner copies only the code. |
| F9 | Low | In the CR timeline, `mdHtml` (`ext_cr_detail.js:219`) sends only fence or draft text to `mdBlock`. Other `>` quotes stay inline `&gt;` there while the modal shows a real blockquote. | Plain quote in a CR timeline entry → `&gt; …` inline. | No change: known gap, same as base. Mention it in the commit message. | n/a | n/a |
| F10 | Info | B2's "−3.1% first-seen" figure doesn't reach the dollar total for main transcripts. On 100 sessions, first-seen $ equals last-seen $ to the cent (output is monotone in 12,789/12,789 multi-line ids; input and cache fields constant). Last-wins is still correct. | — | Keep last-wins. Don't present D4 as a real undercount without agent-file evidence. | Wording only. | Keep `test_cost_last_usage_per_message_id_wins`. |
| F11 | Info | Prices for haiku-5-5 (both tiers), haiku-4-5, opus 4.x and fable 5.1 have no new-format cost-state record to check against. Old-format records (no 5m/1h split) give ratios 0.62–0.90 even when every write is charged at the 1h rate. | — | The F1 fixture covers what can be checked. Leave the rest with their fetched-on date. | — | — |

**Not over-engineered:** most of the plan is the right size. Two small cuts: the speculative
`agents_bg[].cost_usd` row field (§B3: "the Agents panel may show it later") should be built only
because `cost.agents[]` needs it, not as a public row field. The `"+?"` chip suffix plus a
separate `unpriced` list is fine.

### Clean plan

The plan above stands, with these deltas (everything not named is unchanged):

1. **§0 Data facts, add:** (a) Claude `cost-state` lines (shape in F1), with the CLI's total
   including sub-agents. (b) Auggie `billing_metadata.cost_usd` on every exchange (string, its own
   response node, exactly 1.3× list) and session `subAgentCostUsd`. (c) 1,493 usage ids shared
   across forked/continued transcripts. (d) 51/111 jobs blocked/blocked, many with dead workers.
2. **A1:** enum becomes `("summary","narration","prompt")`, default `summary` (F4). Ask the user
   D1 first; if they say "two options only", drop `prompt` (−2 lines).
3. **A2:** `job_for(sid, live)`. `parse_session` calls `_live_daemon_shorts()` once. A non-`done`
   band whose short is not live → `band=label=None`, text kept (F3). Remove the JOBS_DIR-mtime memo
   fallback from A2 and §F.4 (F7).
4. **A3 `headline()`:** a `mode=="prompt"` branch returning `overview.goal` (F4). Otherwise
   unchanged.
5. **A4:** also render `headline` in classic as an `ov_hl` row in the Overview card (`app.js:1979`
   + `index.html`) (F5).
6. **B2:** also capture `cost_state` (last `type:"cost-state"`, cleared by any later usage line)
   into `_PASS_NAMES`. `cost_summary(..., reported=cost_state)` → `cost.reported_usd`, plus one
   modal row (F1).
7. **B4 (Auggie) rewritten:** `main_usd` = sum of `float(billing_metadata.cost_usd)`;
   `agents_usd` = `subAgentCostUsd`; tokens still folded for the breakdown. Savings priced by
   aliasing `-<n>k` → base model; basis "Augment-recorded USD (≈1.3× Anthropic list)". **D3 is
   withdrawn** (F2).
8. **B5 shape:** add `"reported_usd": float|null` and `"basis"` per source. Note text for
   continued sessions (F6).
9. **C2:** `copyCode` uses `:scope > .cpsrc`; CSS offsets a nested fence button (F8).
10. **§E tests:** replace `test_price_table_rows_match_pricing_page` with
    `test_price_table_matches_cli_cost_state` (F1). Replace `test_auggie_cost_unpriced_with_note`
    with `test_auggie_recorded_cost_and_subagents` plus its negative (F2). Add
    `test_dead_blocked_job_keeps_text_drops_pill` (F3), `test_prompt_mode_shows_last_prompt`
    (F4, both providers), classic `ov_hl` node test (F5), `test_continued_session_cost_note` (F6),
    `test_fence_inside_draft_quote` (F8). The self-check's Auggie assertion becomes
    `cost.total_usd > 0` (recorded $) instead of key-presence only.
11. **§G decisions:** D1 moves to the top as the question to ask first. D3 is removed. Add D7:
    "Claude $ is a live list-price recompute; Claude Code's own exit figure is shown beside it
    when available".
12. **Sequencing unchanged.** F1/F2 land in step 2, F3/F4 in step 3, F5 in step 4, F8 in step 5.

## Reconciled plan + verdict table

### Orchestrator verdicts on the review (2026-11-13)

| F | Verdict | Decision |
|---|---|---|
| F1 | confirmed | Accept: keep live recompute; add a test pinning the price table against a real-shape `cost-state` fixture (opus-5-5/sonnet-5-5/sonnet-5 at 1.000×); show "Claude Code reported $X at last exit" in the cost modal when a `cost-state` line exists. |
| F2 | confirmed | Accept: Auggie fills cost from `billing_metadata.cost_usd` (string → float) and agents from `subAgentCostUsd`; D3 withdrawn. Label Auggie's figure as billed (it is 1.3× list), not list price. |
| F3 | confirmed | Accept: keep the summary text; drop the band pill when the job's worker is not live (same live gate as `_blocked_jobs`). |
| F4 | overengineered fix | Reject the third `prompt` option. The user's verbatim ask names two choices — "the last narration message or this kind of summary". `HEADER_LINE` ∈ {summary (default), narration}; non-job sessions fall back to narration. |
| F5 | confirmed | Accept: classic view renders the same server `headline` (parity ruling). |
| F6 | confirmed | Accept as a note in the cost modal only (forked/continued transcripts include the parent's spend); no parent re-parse. |
| F7 | confirmed | Accept: do not build the JOBS_DIR-mtime memo; the per-poll scan with per-file `file_pass` caching is enough. |
| F8 | confirmed | Accept: test only (fence inside a draft quote → outer + inner button both work, no overlap). |
| F9 | confirmed | Accept: no change, known gap; mention in commit message. |
| F10 | confirmed | Accept: wording only; keep last-wins dedupe; don't claim a $ undercount (D4 dropped). |
| F11 | confirmed | Accept: leave unverifiable prices with their fetched-on date. |

Not examined by plan or review: none flagged beyond F11's unverifiable prices and the unexplained `4405110a`/`7d44ec42` CLI-vs-recompute divergences (keep as known gap; the F1 modal line makes the divergence visible to the user).

### Reconciled plan
The reconciled plan is the revised ## Plan above (revision 2, 2026-11-13); deltas: F1 — B2 captures the last trailing `cost-state` into `_PASS_NAMES`, `cost.reported_usd` + one modal line, price test pinned to real `costUSD` records; F2 — B4 rewritten: Auggie $ = Σ`billing_metadata.cost_usd` + `subAgentCostUsd`, basis "Billed by Augment", `-500k` alias for savings only, D3 removed; F3 — `job_for(sid, live)` drops the band pill for non-`done` jobs whose worker isn't live, text kept; F4 — rejected, HEADER_LINE stays {summary, narration} (D1 now records this); F5 — A4b classic `ov_hl` row renders the same `headline`; F6 — seam appends a "copied history" `cost.note` for continued sessions; F7 — JOBS_DIR memo removed from A2 and §F.4; F8 — test only (`test_fence_inside_draft_quote`), no code/CSS change needed (72px quote padding + per-parent `.cpsrc`); F9 — no change, known gap noted in C3 for the commit message; F10 — wording: last-wins kept, no $-undercount claim, D4 removed; F11 — unverifiable prices keep their fetched-on date (§F.2); review cut — `agents_bg[].cost_usd` public row field dropped (cost stays on the cached entry).

## Final adversarial review (opus) on ee25e22 — findings to fix (user: "fix all the issues found directly")

### Client half (verdict: refuted narrowly)
- **CF1 Medium — fixed (test_session_cost: test_auggie_no_usage_no_sub_total_is_null, test_auggie_sub_only_still_priced; test_header_and_cost_ui: test_auggie_session_with_no_usage_has_no_cost_chip)** — zero-usage Auggie session shows a "$0.00" chip (plan B6: no usage → hidden); 10/88 real sessions. Cause: `auggie.py` always passes `recorded=(rec_usd, sub)`, so `util.cost_summary` yields 0.0. FIX: server emits `total_usd: null` when nothing recorded — `recorded=(rec_usd, _sub_agent_usd(d)) if (cost_tok or rec_usd or _sub_agent_usd(d)) else None`; client must NOT infer hidden-from-zero. TEST: test_session_cost Auggie fixture with no exchanges/subAgentCostUsd → `total_usd is None`; test_header_and_cost_ui `statChipsHtml` on that payload has no `data-act="cost"`.
- **CF2 Low — fixed (test_draft_copy: test_multi_paragraph_draft_copies_every_paragraph)** — a draft split by a bare blank line (`**Draft reply:**\n\n> Hi team,\n\n> Second para.`) copies only the first paragraph; lazy continuation lines are dropped. FIX: in mdBlock's `>` branch (app.js ~:231), when `draftLabelBefore` is true, look past blank lines; if the next line matches `^\s*>`, push "" and keep collecting. Fences/lists/plain quotes unchanged. TEST: test_draft_copy `multi_para_noblank` → cpsrc == "Hi team,\n\nSecond para.", exactly one `cblock dq`.
- **CF3 Low — fixed (test_draft_copy: test_has_draft_quote_agrees_with_mdblock_for_nested)** — `hasDraftQuote` (app.js ~:182) is false for `> **Draft x**\n> > inner` while mdBlock renders a button (CR timeline vs modal disagree). FIX: recurse on de-prefixed quote lines as mdBlock does. TEST: add to the `has` array.
- **CF4 Low — fixed (test_header_and_cost_ui: test_delegated_handler_opens_the_modal, test_classic_cost_chip_present drive the real handler/onclick under node; CSS check cut)** — grep-only tests (test_classic_cost_chip_present, test_delegated_handler_opens_the_modal, test_config_dialog_has_header_line_row, WiringTests, test_integration.py:1464). FIX: drive the CR click switch `case "cost"` with a fake `ui.lastSession` and assert `openText` is called; drive the classic chip click likewise. (Computed-style phone CSS check: skipped as optional.)
- **CF5 risk — fixed (test_draft_copy: test_copycode_uses_cpsrc_and_textarea_fallback)** — iOS http fallback calls `select()` on a `readonly` textarea → may not select yet shows "Copied". FIX: use the same non-readonly hidden-textarea approach as `copyNote`, and show "Copied" only when `execCommand` returns true. TEST: node test asserts the fallback textarea is not readonly and the failure path does not show "Copied".

### Server half (verdict: unproven — main path verified vs independent recompute; agent-pass dedupe untested)
- **SF1 Medium — fixed (test_session_cost: ClaudeCostTests.test_agent_last_usage_per_message_id_wins; red under key mutation: 508 != 387)** — agent-pass last-wins dedupe (`providers/claude.py:1265`) has no test: mutating the key to always-unique keeps 13/13 + selfcheck green while real session dbf99e3a's agents $ goes 2.531 → 4.0675. FIX: tests only, do NOT change the key rule. TEST: new `test_agent_last_usage_per_message_id_wins` — agent-x.jsonl repeats `_asst("a1",…)` 3× with output 1→120→287 plus one id-less line; assert agents row out == 387 and `agents_usd` equals the last-wins figure. Red under that mutation.
- **SF2 Low — fixed (test_session_cost: SeamTests.test_fork_note_on_provider_without_cost; KeyError before)** — `registry.py:179-180` mutates `d["cost"]` before the seam default `setdefault("cost", …)` at :212 → KeyError/500 for a provider without cost + truthy `continued_from`. FIX: move those lines below :212; note text/condition unchanged. TEST: SeamTests monkeypatches `registry.fork_parent_of` → "p" for an augment-vscode id; assert "copied" in `d["cost"]["note"]` (KeyError before).
- **SF3 Low — fixed (test_session_cost: AuggieCostTests.test_auggie_bad_cost_string_skipped now expects main_usd None)** — `auggie.py:600` counts an unparseable `cost_usd` as 0, and usage-without-billing shows $0.00; `test_auggie_bad_cost_string_skipped` (:183) pins it. FIX: count successfully-parsed billing values (`n_billed`).

### Orchestrator reconciliation (CF1 + SF3 touch the same `auggie.py` `cost_summary(...)` call — one rule)
| Auggie session | `recorded` passed | Result |
|---|---|---|
| no exchanges, no `subAgentCostUsd` | `None` | `total_usd: null` → chip hidden (CF1) |
| usage/exchanges but no parseable `cost_usd` | `(None, sub)` | `main_usd: null` → unpriced, never $0 (SF3) |
| ≥1 parseable `cost_usd` | `(rec_usd, sub)` | billed total |

Verdicts: CF1–CF5, SF1–SF3 all **confirmed**; CF4's optional computed-style CSS check **cut** (wider than the defect). Change `test_auggie_bad_cost_string_skipped` to expect `main_usd is None`.
