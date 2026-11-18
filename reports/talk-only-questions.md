# Talk-only timeline filter includes questions/decisions

Branch: `talk-only-questions` (worktree `.claude/worktrees/resume-panel-format`, cut from `personal/main` @ ad0f817)

## Contract (verbatim, user, 2026-11-18)

> the talk-only section in the narration tab must include the questions/decisions as well. only plan->fix->review for this, only 1 review at the end after the fix, thats the chain, all the stages needs to go in with /tracker-gap and /gap, ->  /branch-sync --> hold /tracker-push

| Clause | Status |
|---|---|
| Talk-only filter shows question/decision (`ask`) entries | not discharged |
| Chain: plan → fix → one review after the fix | not discharged |
| Every stage under /tracker-gap + /gap | not discharged |
| /branch-sync | not discharged |
| Hold /tracker-push (do NOT push to main) | not discharged |

Screenshots: under "all", the "IT ASKED YOU · STILL OPEN" card (kind `ask`) shows; under "talk only" it is missing.

### Contract addendum (verbatim, user, 2026-11-18)

> can I have all the questions asked and shown to the tracker display which can be easily scrollable via left arrow and the right arrow, imitationg the similar behavior like the claude code terminal when you use

_Note: message truncated as received; read as "…when you use AskUserQuestion" (Claude Code's tabbed question header, ← ☐ Q1 ☐ Q2 … →)._

| Clause | Status |
|---|---|
| Every question of a multi-question decision is shown (not only `questions[0]`), pageable with ←/→ like Claude Code's AskUserQuestion | not discharged |

## Starting facts (main thread)
- Seam: `timelineEntryVisible(e, ui)` in `aitracker/web/ext_cr_detail.js` (~line 3478): talk preset = `e.kind === "prompt" || e.kind === "narration"`.
- A NOTE comment above it (~3464) documents ask being deliberately excluded from talk-only — superseded by this contract.
- `timelineEmptyMessage` talk text: "No prompts or narration recorded yet".
- `tests/test_cr_timeline.py:420` `test_talk_only_is_unchanged_prompt_and_narration_only` asserts ask NOT in talk-only — must flip.

## Plan
_Author: opus plan agent, 2026-11-18. Grounded by grep + `sed -n` ranges at ad0f817._

### Entry-point census (the gap is ONE seam)
- **The only talk filter anywhere** is `timelineEntryVisible(e, ui)` — `aitracker/web/ext_cr_detail.js:3479-3489`, talk branch at `:3488`. `grep -rn 'timelineFilter\|"talk"\|talk only\|alk-only' aitracker tests` finds nothing else in any `.py`, `app.js` or other `ext_*.js` (only CSS comments at `ext_cr_detail.css:1409,2131,2134` — sizing notes, no behaviour).
- Every consumer already flows through that predicate, so they agree automatically once it changes:
  - render: `renderTimelineEntries` `:3547` `filtered = all.filter(timelineEntryVisible)` → `ui.timelineEntries = filtered` `:3550`; empty state `:3560` → `timelineEmptyMessage(ui)`.
  - pop-out / prev-next / "latest": `openTimelineEntry` `:3628`, `openTimelineEntryByKey`, `openLatestTimelineEntry`, the panel pop-out button (`data-act="timeline-popout"` `:1664`, handler `:1979`) — all read `ui.timelineEntries`. `_setNav`'s `len()` is live over the same list.
  - modal payload for an ask already exists: `timelineEntryModalPayload` `:3599` (`e.kind === "ask"`). Card render: `entryHtml` `:3318`.
  - preset button state: `updateTimelineFilterButtons` `:3492-3501` — kind-agnostic, no change.
- **No server-side filter.** `ask` entries are built client-side by `mergeTimeline` `:778-781` from the shared detail-dict field `decisions` (kind name confirmed: `"ask"`). Producers: Claude `providers/claude.py:2494` (open asks `:2366`, closed/answered `:2264-2265` set `open:false` + `answer`); Auggie `providers/auggie.py:776` (same shape, closed at `:598-599`); `auggie.py:503` and `providers/augment_ext.py:277` emit `decisions: []`.
- **Provider degrade:** `mergeTimeline` uses `(session.decisions || [])` and the predicate is kind-only, so a provider with no decisions just shows prompts+narration under talk-only — nothing to guard beyond what exists. Open vs closed is irrelevant to the predicate (both are kind `ask`), so closed/answered decisions show too.

### Change (shortest diff — `aitracker/web/ext_cr_detail.js` only)
1. **Predicate `:3488`:**
   `return ui.timelineFilter === "talk" ? (e.kind === "prompt" || e.kind === "narration" || e.kind === "ask") : true;`
   Also update the inline comment `:3487` ("defer to the all/talk preset; talk = prompts, narration and questions/decisions").
2. **NOTE comment `:3464-3472`:** rewrite — `ask` still maps to none of the four chips (chips unchanged), but the **talk-only preset now includes `ask`** (user contract 2026-11-18: "the talk-only section … must include the questions/decisions as well"). Drop the "owner said not to touch talk-only" sentence; keep the "a fifth questions chip would be the clean way" sentence.
3. **Empty message `:3514`:** `emptyHtml("No prompts, narration or questions recorded yet", "Talk-only shows what was said and asked.")`.
4. **Export `:3766` block:** add `timelineEmptyMessage: timelineEmptyMessage,` next to `timelineEntryVisible` (test access only).

No `.py` change, no CSS change, no new chip, `TIMELINE_KIND_MAP` untouched.

### Tests — `tests/test_cr_timeline.py` (each new/flipped assertion is RED on ad0f817)
1. **Flip** `test_talk_only_is_unchanged_prompt_and_narration_only` `:420-422` → rename `test_talk_only_shows_prompts_narration_and_questions`; assert `sorted(OUT["talkOnly"]) == ["ask", "narration", "prompt"]` and `"command"`, `"command-fail"`, `"tool"` not in it. RED today (no `ask`).
2. **Add closed + open decisions fixture** (keeps `_mixed_detail` untouched so `popoutListLen == 6` `:452` and `allDefault` stay valid): new `_decisions_detail()` using `make_detail(requests=[…1 prompt…], decisions=[{"t":…, "open": False, "answer": "a", "questions":[{"q":"pick?","options":["a","b"]}]}, {"t":…, "open": True, "answer": "", "questions":[…]}])` (real shape, `claude.py:2264-2266,2366`). Pass as a third `%s` in the driver format at `:238`; in JS: `OUT.talkDecisions = mergeTimeline(decisionsDetail).filter(e => timelineEntryVisible(e, {timelineFilter:"talk", timelineKindsOn:{}})).filter(e => e.kind==="ask").map(e => e.decision.open);` New test `test_talk_only_shows_open_and_answered_decisions`: `sorted(OUT["talkDecisions"]) == [False, True]`. RED today (empty list).
3. **Empty message:** driver `OUT.talkEmpty = window.CR.detail._internal.timelineEmptyMessage({timelineFilter:"talk", timelineKindsOn:{}});` New test `test_talk_only_empty_message_names_questions`: `assertIn("questions", OUT["talkEmpty"])`. RED today (export missing → driver throws, and old text lacks "questions").
4. **Keep unchanged:** `test_ask_is_excluded_from_every_kind_chip` `:436` (chips still exclude ask — guards that this change didn't leak into chips), `test_default_all_shows_every_kind_including_ask`, chip tests, provider-parity test.
5. Comment touch-ups only: driver comment `:188` and class comment `:412` "talk-only unchanged" → "talk-only = prompts + narration + questions".

Red proof: implementer applies the test edits first, runs the gate (expect 3 failures), then the JS edits (expect green); or reverts the `:3488` line after and watches tests 1–2 go red.

### Gate
`unset TRACKER_AUTH; python3 -m unittest tests.test_cr_timeline` (needs `node`; skips otherwise — confirm it actually RAN, not skipped), then `unset TRACKER_AUTH; make check` → `selfcheck ok` (Bash timeout >2 min; `Killed: 9` = OOM, rerun per-module; one known flaky term_vt backstop). Restart needed to see it live (`make serve`) — this is a UI change (page baked at startup).

### Risky spot + fallback
- **Chip vs preset semantics diverge:** "prompts"+"narration" chips together ≠ talk-only any more (talk-only now also has asks). Intended; pinned by keeping the chips-exclude-ask test. Fallback if the user wants parity: add a fifth `questions` chip (`TIMELINE_KIND_MAP.questions = ["ask"]`) — not done here, not asked for.
- **Duplication with the Decisions panel:** an open ask already appears both in the Decisions panel and the timeline under "all"; talk-only now matches "all" in that respect — no new duplication class.
- Harness risk: `timelineEmptyMessage` → `emptyHtml` (`:268`) must run under the Node stub DOM; if it touches a DOM API the stub lacks, fall back to asserting on the source text of `:3514` via the bundle string (or drop test 3 — it is cosmetic).

### Decisions the user may overrule
1. **No fifth "questions" chip** — talk-only gains asks; the four chips are untouched.
2. **Answered/closed decisions show under talk-only too** (not only "still open") — the predicate is kind-based, matching the contract's "closed/answered decisions too".

## Plan v2 — question pager
_Author: opus plan agent, 2026-11-18. Grounded by grep + `sed -n` ranges on the worktree (Plan v1 edits present, uncommitted — kept as-is; v2 lands on top of them in the same branch)._

### Findings (how a decision's `questions[]` renders today)
- **Real shape confirmed** from a live `~/.claude/projects/**.jsonl` (keys only): `AskUserQuestion` input `{questions:[{question, header, multiSelect, options:[{label, description}]}]}`, seen with **4 questions** in one call. The answer record carries `toolUseResult = {questions, answers, annotations}` where `answers` is a **dict keyed by full question text → string** (213 str values sampled, every key matched a question). The `tool_result` text is `<prefix> "Q1"="A1", "Q2"="A2", … <boilerplate>`; two prefixes exist in the wild: `Your questions have been answered:` (90 files) and `The user answered:` (63 files) — the parser (`providers/claude.py:2264`) strips only the first.
- **Producer shape** (`claude.py:2361-2365`): `questions:[{q, header, options[]}]`, one shared `answer` string per decision; no per-question answer, `multiSelect`/option `description` dropped. Auggie (`auggie.py:675-677`) always emits **exactly one** question (`ask-user` has one `question` + `suggested_responses`); `auggie.py:503` / `augment_ext.py:277` emit `decisions: []`.
- **Every Control-Room renderer shows only `questions[0]`** — five forks of the same `q0 = (d.questions && d.questions[0]) || {q:"",options:[]}` line, no shared renderer:
  1. timeline card — `entryHtml` ask branch, `aitracker/web/ext_cr_detail.js:3318-3333`
  2. Decisions & Open Questions panel — `renderDecisions` → inner `renderQ`, `:2784-2813` (`:2792`)
  3. phone "Waiting on you" card — `renderPhoneAwaiting`, `:1170-1190` (`:1176`)
  4. ask modal / pop-out / prev-next — `timelineEntryModalPayload`, `:3595-3604` (`:3597`); reached from the card (`data-act="timeline-entry-open"` `:1982`) and the panel pop-out (`timeline-popout` `:1979`) via `openTimelineEntry` → `openText`
  5. spine marker tooltip — `buildMarkers`, `:707-711` (title = q0 only)
  - (Classic UI `app.js:2162-2177` already stacks **all** questions with `header` — the only renderer that does; out of scope, left alone.)
- **Key collisions:** `app.js:2886-2890` — document-level `ArrowLeft/ArrowRight` = `navModal(±1)` (prev/next timeline entry) **whenever `#msgmodal`/`#diffmodal` is open**. `ext_cr_board.js:3152` j/k/Esc only when the board is active (`isBoardActive()`), not in detail. `ext_vt.js` terminals eat arrows inside their own input. Detail's own `node` keydown `:1763` handles only Enter/Space on role=button headers. ⇒ arrows are free inside the detail view **except** while the classic modal is open.
- **Re-render cadence:** `renderDecisions` and `renderPhoneAwaiting` rewrite `innerHTML` on **every 2 s poll** (`renderUpdate` `:2323-2324` → `setPanelBody` `:1324`), which drops focus. The timeline repaints only when the filtered count changes or `force` (`:3552`). `ui` is created once per page load (`:1582`) and cleared on `session:reset` (`:1783-1800`).

### The seam
One shared renderer in `ext_cr_detail.js`, `questionPagerHtml(d, ctx, ui, optCls)`, used by the three HTML surfaces (card, panel, phone card) **only when `d.questions.length > 1`**; the existing single-question markup in each caller stays byte-for-byte (so Auggie and every 1-question Claude ask render unchanged). Page state lives in `ui.qPage[qKey(d)]`; paging is a **DOM toggle** (all panes are in the markup, one visible), never a re-render — so focus and the 2 s poll don't fight. Per-question answers are data, so they are added **server-side** on the shared detail shape (rule 5), not parsed out of the answer string in JS.

### Change — files : functions (sequenced)

**1. `aitracker/providers/claude.py` — the `tool_result` branch `:2263-2265`** (lands first; the UI reads its field but degrades without it):
```python
if rid in asks:
    asks[rid]["answer"] = re.sub(r"^Your questions have been answered:\s*", "", rtext).strip()[:2000]   # unchanged
    asks[rid]["open"] = False
    ans = r_.get("answers") if isinstance(r_, dict) else None        # r_ = o.get("toolUseResult"), already bound at :2169
    if isinstance(ans, dict):
        by_q = {str(k)[:500]: v for k, v in ans.items()}             # q text is stored [:500] at :2361
        for q in asks[rid]["questions"]:
            v = by_q.get(q["q"])
            if isinstance(v, str):
                q["answer"] = v[:500]
```
Shape becomes `questions:[{q, header, options[], answer?}]` — additive, optional; Auggie never sets it. Update the shape comment `ext_cr_detail.js:38` to `questions:[{q,header,options[],answer?}]`.

**2. `aitracker/web/ext_cr_detail.js` — new helpers (place just above `entryHtml`, ~`:3275`), ES5 `var` style like the file:**
- `qKey(d)` → `String(d.t || "") + "#" + (d.questions || []).length` — stable across the open-first re-sort (the timeline key `"a"+i` is index-based and shifts when an ask is answered, so it can't hold state).
- `qPageStep(i, dir, n)` → **clamp**: `Math.max(0, Math.min(n - 1, i + dir))` (no wrap — matches Claude Code's header and `navModal`'s own clamp at `app.js:2330`).
- `questionPagerHtml(d, ctx, ui, optCls)` → markup:
```html
<div class="crd-qpager" data-qkey="KEY" data-qn="3" role="group" aria-label="3 questions">
  <div class="crd-qpager-head">
    <button class="crd-qpager-step" data-act="qpage-step" data-dir="-1" aria-label="Previous question" [disabled at 0]>‹</button>
    <div class="crd-qpager-tabs" role="tablist">
      <button role="tab" class="crd-qpager-tab is-cur [is-answered]" data-act="qpage-go" data-i="0" aria-selected="true">☒ HEADER-or-"Q1"</button>
      <button role="tab" class="crd-qpager-tab" data-act="qpage-go" data-i="1" aria-selected="false" tabindex="-1">☐ Q2</button> …
    </div>
    <button class="crd-qpager-step" data-act="qpage-step" data-dir="1" aria-label="Next question" [disabled at n-1]>›</button>
    <span class="crd-qpager-pos mono">1/3</span>
  </div>
  <div class="crd-qpager-pane" data-i="0">  <!-- others carry hidden -->
    <div class="crd-qpager-q">mdHtml(ctx, q.q)</div>
    <div class="crd-qpager-opts">…'<span|div class="' + optCls + '">' + mdHtml(ctx, o) …</div>
    [q.answer ? '<div class="crd-qpager-answer">Answered: ' + mdHtml(ctx, q.answer) + '</div>' : ""]
  </div> …
</div>
```
Box glyph: `☒` when the question has its own `answer` (or the decision is closed and none have per-question answers), else `☐`. Tab label = `esc(q.header) || "Q" + (i+1)`. Index = `qPageStep(ui.qPage[key] || 0, 0, n)` (clamps a stale index). `ui` may be undefined (tests, other callers) → index 0.
- `applyQPage(pagerEl, i)` → toggles `hidden` on `.crd-qpager-pane`, `is-cur`/`aria-selected`/`tabindex` on `.crd-qpager-tab`, `disabled` on the two `.crd-qpager-step`, text of `.crd-qpager-pos`. No innerHTML.
- `goQPage(node, ui, key, i)` → `ui.qPage[key] = i`, then `applyQPage` on **every** `.crd-qpager[data-qkey="key"]` in `node` (the same decision can be on the timeline card and in the panel at once — they stay in sync).
- `qPagerOnKey(ev, ui, node)` → returns true when handled. Handles only `ArrowLeft`/`ArrowRight` with no meta/ctrl/alt; only when `ev.target.closest(".crd-qpager")` (focus is inside a pager — a tab, a ‹ › button, or the pager itself); bails if `document.getElementById("msgmodal")` / `"diffmodal"` has `style.display === "flex"` (the modal owns arrows). On handle: `goQPage(...)`, focus the new current tab, `preventDefault()` + `stopPropagation()`.
- `focusedQKey(container)` / `refocusQ(container, key)` → read `document.activeElement.closest(".crd-qpager")`'s `data-qkey` before a repaint; after it, focus that pager's `.crd-qpager-tab.is-cur`.

**3. Wire the entry points (same file):**
- `entryHtml(e, ctx, diagram, ui)` (`:3279`; add 4th param; caller `renderTimelineEntries` `:3555` passes `ui`): in the ask branch, if `(d.questions||[]).length > 1` replace the `crd-ask-q` + `crd-ask-opts` pair with `questionPagerHtml(d, ctx, ui, "crd-ask-pill")`; mini-head and view-only note unchanged. Else the current markup.
- `renderTimelineEntries` repaint block `:3552-3560`: wrap with `var fk = focusedQKey(scrollEl); … refocusQ(scrollEl, fk);`.
- `renderDecisions(wrap, session, ui)` (`:2784`; call site `:2323` passes `ui`): `renderQ` uses the pager for >1 question with `optCls "crd-decision-opt"` — for **open AND closed** decisions (closed currently hides options; in the pager a closed decision shows each question + its per-question answer, options hidden like today: pass a flag `showOpts = isOpen`). The whole-decision `Decided: …` line stays, but is omitted when every question has its own `answer`. Then: `if (wrap._qHtml !== html) { var fk = focusedQKey(wrap); setPanelBody(wrap, html); wrap._qHtml = html; refocusQ(wrap, fk); }` — skip identical repaints (stops the 2 s focus loss), restore focus when a page change alters the html.
- `renderPhoneAwaiting(node, session, ui)` (`:1170`; call site `:2324`): for >1 question, replace the `crd-phone-awaiting-q` + opts with `questionPagerHtml(d, null, ui, "crd-phone-awaiting-opt")`; same `_qHtml` skip + refocus on `card`.
- `timelineEntryModalPayload(e)` (`:3595`): for >1 question, **stack all** (markdown can't hold a pager, and ←/→ already page entries in that modal): per question `"**" + (i+1) + "/" + n + (header ? " · " + header : "") + "** — " + q.q`, its `- option` lines, and `"Answered: " + q.answer` when present; then the existing Decided/view-only footer (Decided omitted when every question has its own answer). 1-question branch byte-identical.
- `buildMarkers` (`:710`): title `q0.q + (n > 1 ? " (+" + (n-1) + " more)" : "")`.
- Click delegation (`:1805` switch): `case "qpage-go"`: `goQPage(node, ui, pagerKey, +t.getAttribute("data-i"))`; `case "qpage-step"`: `goQPage(node, ui, key, qPageStep(cur, +data-dir, n))`, where `pager = t.closest(".crd-qpager")`. Because these buttons carry their own `data-act`, `closest("[data-act]")` hits them before the card's `timeline-entry-open` — a tab click never opens the modal.
- Keydown: in the existing `node.addEventListener("keydown", …)` (`:1763`), first line `if (qPagerOnKey(ev, ui, node)) return;`.
- `session:reset` (`:1785`): add `ui.qPage = {};` and init `qPage: {}` in the `ui` literal (`:1582`).
- `_internal` export (`:3747`): add `entryHtml, questionPagerHtml, qPageStep, qKey, applyQPage, qPagerOnKey` (test access; `renderDecisions`, `timelineEntryModalPayload` already exported).

**4. `aitracker/web/ext_cr_detail.css`** (next to `.crd-ask-*` ~`:1625-1642`): `.crd-qpager-head{display:flex;align-items:center;gap:6px}` · `.crd-qpager-tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;flex:1;min-width:0}` · `.crd-qpager-tab{white-space:nowrap;font:inherit;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line-subtle);background:none;color:var(--text-secondary)}` · `.crd-qpager-tab.is-cur{color:var(--text-primary);border-color:currentColor;font-weight:600}` · `.crd-qpager-step:disabled{opacity:.35}` · `.crd-qpager-pos{font-size:10.5px;color:var(--text-muted)}` · `.crd-qpager-answer` = `.crd-decision-answer` look · `.crd-qpager:focus-within{outline:1px solid var(--line-subtle);outline-offset:2px}`. In the existing `@media (max-width: 600px)` block (`:1893`): `.crd-qpager-step,.crd-qpager-tab{min-height:44px;min-width:44px}` (touch target, same as `.crd-decision` `:2204`). No host gating — same markup and handlers on desktop/tablet/phone; touch uses tabs + ‹ ›, keyboards add ←/→.

No new dependency, no `app.js` change, no new route, Auggie provider untouched.

### Tests (each RED on the current worktree, before the v2 code)
`tests/test_cr_timeline.py` (node driver; add a `_multi_q_detail()` fixture: one **open** 3-question decision and one **closed** 2-question decision whose questions carry `answer`, plus one 1-question decision; pass as another `%s` into `_driver_js`):
1. `test_card_pager_renders_every_question` — `entryHtml(askEntry3, null, null, {qPage:{}})` contains `crd-qpager`, all three question texts, all three tab labels, exactly one pane without `hidden`. RED: export missing / only Q1 present.
2. `test_card_pager_respects_ui_page` — with `ui.qPage[qKey(d)] = 2`, pane index 2 is the only visible one and the position reads `3/3`; stale `qPage = 9` clamps to the last pane.
3. `test_qpage_step_clamps` — `qPageStep(0,-1,3)==0`, `(2,1,3)==2`, `(0,1,3)==1`.
4. `test_arrow_key_moves_page_only_inside_a_pager` — fake event `{key:"ArrowRight", target:{closest: s => s===".crd-qpager" ? fakePager : null}, preventDefault, stopPropagation}` → `qPagerOnKey` returns true, `ui.qPage[key]==1`, preventDefault called; `key:"j"` → false; `closest` → null → false; with `document.getElementById("msgmodal").style.display="flex"` → false (modal keeps ←/→). `fakePager` = `{getAttribute(k)…, querySelectorAll(sel)→ recorded fake els}`; `node.querySelectorAll` returns `[fakePager]`.
5. `test_single_question_ask_renders_unchanged` — `entryHtml` for the 1-question decision has no `crd-qpager` and still contains `crd-ask-q` + `crd-ask-pill` (green before and after: a guard, not a red test — say so).
6. `test_decisions_panel_pages_open_and_closed_multi_q` — `renderDecisions(fakeWrap, multiQDetail, {qPage:{}})` (fakeWrap whose `.crd-panel-body` records `innerHTML`): HTML contains a `crd-qpager` per multi-q decision, every question text, the closed one's per-question `Answered:` lines, and **no** whole `Decided:` line for it.
7. `test_modal_payload_lists_every_question` — `timelineEntryModalPayload` for the 3-q ask: text contains `1/3`, `2/3`, `3/3` and all three questions; for the 1-q ask the payload equals today's exact string (pin it).
8. `test_auggie_and_empty_degrade` — an Auggie-shaped decision (1 question, no `header`, no per-q `answer`) renders today's markup; `questions: []` → no throw, no `crd-qpager` (q0 fallback path); `decisions: []` panel → empty state unchanged.

`tests/test_integration.py` (beside `test_claude_decisions` `:1227`): `test_claude_multi_question_answers` — a `tool_use` with 2 questions + a `user` record whose `toolUseResult.answers = {"Q1 text": "A", "Q2 text": "B"}` → `dec["questions"][0]["answer"]=="A"`, `[1]["answer"]=="B"`; a result without `toolUseResult` leaves no `answer` key (degrade). RED: field absent.

Red proof: implementer writes tests first and runs them (expect 1-4, 6-8 + the integration test to fail; 5 green), then the code; then reverts the `questionPagerHtml` call in `entryHtml` and the `answers` loop in `claude.py` and watches 1, 6 and the integration test go RED again. Never `git stash` (shared stack) — revert with a scoped Edit.

### Gate
`unset TRACKER_AUTH; python3 -m unittest tests.test_cr_timeline tests.test_integration` (confirm it RAN, not skipped for missing `node`), then `unset TRACKER_AUTH; make check` → `selfcheck ok` (Bash timeout > 2 min; `Killed: 9` = OOM → rerun per module; one known flaky term_vt backstop). UI + parse change → restart (`make serve`) to see it.

### Risky spot + fallback
- **Focus loss on the 2 s repaint** (Decisions panel, phone card) is what would make ←/→ "stop working" after a moment. Mitigation: `_qHtml` identical-html skip + `focusedQKey/refocusQ` around every repaint; paging itself never repaints. Fallback if focus still drops on some browser: document-level arrow handler scoped to `:hover`/last-clicked pager key (`ui.qActive`), still gated off while `#msgmodal` is open.
- **Arrow collision with the classic modal** (`app.js:2886`): `qPagerOnKey` bails while the modal is open, so ←/→ there keep paging entries; the modal shows all questions stacked instead. If the user wants ←/→ to page questions inside the modal too, that needs HTML in `openText` (today markdown-only) — not in this diff.
- **Per-question answer match**: keyed by question text truncated to 500 to mirror `:2361`; any miss just falls back to the whole `d.answer` line. Answers in old transcripts lacking `toolUseResult.answers` (≈13 of ~90 sampled) degrade the same way.
- **`qKey` collision** (two decisions with the same `t` and count) only shares a page index — cosmetic.

### Decisions the user may overrule
1. **Clamp, not wrap** at the first/last question (matches Claude Code and the modal's own prev/next).
2. **Arrows need focus inside the pager** (click a tab or ‹ › first, or Tab to it) rather than "whatever is hovered" — hover doesn't exist on phone/tablet and a global listener would fight the modal and terminals.
3. **Modal/pop-out stacks all questions** instead of paging them (←/→ there already means prev/next entry).
4. **Not fixed here:** the newer `The user answered:` answer prefix and its trailing boilerplate are not stripped by `claude.py:2264` (adjacent bug, 63 real files) — one-regex fix if the user wants it folded in.

## Contract addendum 2 (verbatim, user, 2026-11-18)

> do a research and let me know, then will supersede my initial plan of only running plan->fix->review, instead run the entire chain till /tracker-push hold one for that run /branch-sync

| Clause | Status |
|---|---|
| Research the CLI's AskUserQuestion UX and report it to the user | discharged (`reports/talk-only-questions-research.md`) |
| Full chain replaces plan→fix→review: plan → adversarial plan review → reconcile → user sign-off → implement → implementation review → ship | not discharged |
| Run /branch-sync; HOLD /tracker-push (no push to main) | not discharged |

## Plan review (opus)
_Adversarial reviewer, 2026-11-18. Verified by grep + `sed -n` on the worktree (v1 edits present at `ext_cr_detail.js:3484,3510,3763`) and a keys/types-only scan of every `~/.claude/projects/**/*.jsonl`._

**Real-data facts (scan, this machine):** 438 AskUserQuestion calls — 4q:166, 3q:54, 2q:102, 1q:115, 0q:1 (so **74% are multi-question**; the pager is the common case, not an edge). 37 questions are `multiSelect`. `toolUseResult.answers`: 945 `str` values + **11 `list` values**; every key equals a question text (956/956). 83 answered results carry no `toolUseResult.answers`. Result-text prefixes: `Your questions have been answered:` 228 · `The user answered:` 211. Result-text **tails, never stripped today**: `. You can now continue with these answers in mind.` 230 · `. Read the answers carefully — they may request clarification, changes, or that you not proceed — and follow what they actually say.` 214. `annotations` is non-empty in 5 results only (`preview`/`notes`) — ignore.

**Seam check:** all five `questions[0]` forks are covered by v2 (card `:3320`, panel `:2792`, phone `:1176` → pager; modal `:3597` → stacked; spine `:710` → `(+n more)`); classic `app.js:2167` already stacks every question. No other consumer of `decisions[].questions` exists (`grep -rln decisions aitracker` → only these files). No path is left showing only Q1. Keeping each caller's 1-question markup (instead of routing n=1 through the pager too) is accepted — collapsing it would churn three CSS families for no visible gain.

**Tab / Shift+Tab:** plan correctly does NOT bind them. Hijacking Tab traps keyboard users inside the pager (WCAG 2.1.2); the ARIA tabs pattern uses ←/→ between tabs and Tab to leave. Confirmed, no change.

| # | Sev | Defect (file:line, repro) | Fix direction | Way | Test (red before fix) |
|---|---|---|---|---|---|
| R1 | **High** | Plan step 1 `if isinstance(v, str)` drops multiSelect answers, which are lists (11 real). Repro: `answers={"Q2":["a","b"]}` → Q2 gets no `answer`, tab shows ☐, pane shows no answer, and the decision still shows the raw `Decided:` blob. Expected `answer:"a, b"`. | Accept `str` **and** `list`; MUST NOT change the dict-keyed-by-question-text match. | `claude.py` tool_result branch `:2263-2265`: `if isinstance(v, list): v = ", ".join(str(x) for x in v)`; then `if isinstance(v, str) and v: q["answer"] = v[:500]`. | `test_integration.py::test_claude_multi_question_answers` — add a list answer, assert `"a, b"`. Red with the plan's str-only code. |
| R2 | **High** | Decision `answer` text is half-cleaned: `claude.py:2264` strips only `Your questions have been answered:` and never either tail. Repro (211+214 real): result `The user answered: "Ship?"="Yes". Read the answers carefully — …` → panel/modal/classic show `Decided: The user answered: "Ship?"="Yes". Read the answers carefully — …`. Expected `"Ship?"="Yes"`. v1 makes this worse: talk-only now surfaces every answered decision. | Fold in (planner left it out). Strip both prefixes and both tails server-side; keep the `[:2000]` cap; MUST NOT touch Auggie's `User responded:` path or the `open=False` flip. | `claude.py:2264`: `a = re.sub(r"^(?:Your questions have been answered:|The user answered:)\s*", "", rtext)`; `a = re.sub(r"\.?\s*(?:You can now continue with these answers in mind\.|Read the answers carefully\b.*)\s*$", "", a, flags=re.S)`; `asks[rid]["answer"] = a.strip()[:2000]`. | Extend `test_claude_decisions` (`test_integration.py:1227`): a third ask answered with the `The user answered:` + `Read the answers carefully…` form → `answer == '"Q"="A"'`; and assert the existing `Your questions…` case no longer ends with `in mind.` Red today. |
| R3 | **Med** | Timeline card for a **closed** ask (`entryHtml` `:3318-3334`) shows no answer and always prints `View-only — answer in the session` (`:3333`, unconditional). With v1, every answered 1-question decision in talk-only reads as still answerable. v2 only fixes this for multi-q (pager panes). Repro: closed 1-q decision `answer:"Yes"` → card has no "Yes". | Closed card shows its answer in the CLI's form `→ A`; the "answer in the session" note only while `d.open`. 1-q open markup unchanged. | `entryHtml` ask branch, non-pager path: `var ans = !d.open ? (q0.answer \|\| d.answer \|\| "") : ""`; append `'<div class="crd-ask-answer">→ ' + mdHtml(ctx, ans) + "</div>"` when `ans`; wrap the `crd-ask-note` div in `d.open ? … : ""`. CSS `.cr .crd-ask-answer` = `.crd-decision-answer` look (`ext_cr_detail.css:1096`). | `test_closed_single_question_card_shows_answer`: `entryHtml` of closed 1-q → contains `Yes`, not `answer in the session`. Red today. |
| R4 | **Med** | Focus-gated keys are fragile: (a) WebKit/Safari does not focus a `<button>` on mouse click, so after clicking a tab `ev.target.closest(".crd-qpager")` is null and ←/→ do nothing; (b) node-level keydown (`:1763`) never fires once a repaint drops focus to `<body>`, which forces three helpers (`_qHtml`, `focusedQKey`, `refocusQ`) at three repaint sites. | Replace focus-gating with an **active-pager key in `ui`**, handled in the detail view's existing **document** keydown (`:2146`, already guarded by `isDetailActive` / `isTypingTarget` / open CR dialog). Repaint-proof, no refocus machinery. MUST still bail while `#msgmodal`/`#diffmodal` is open (app.js `:2886` owns ←/→ there) and inside inputs/terminals. | `ui.qActive` (key or null). Click delegation (`:1805`, before the switch): `var pg = ev.target.closest(".crd-qpager"); ui.qActive = pg ? pg.getAttribute("data-qkey") : null;`. `node` `focusin`: same from `ev.target`. In the `:2146` handler, before j/k: `if (qPagerKey(ev, ui, node)) return;`. `qPagerKey` = pure, exported: ArrowLeft/Right, no meta/ctrl/alt/shift, `ui.qActive` set, a `.crd-qpager[data-qkey=…]` exists in `node`, modals closed → `goQPage`, `preventDefault`, return true; if `document.activeElement` is inside that pager, focus its new `.is-cur` tab (`{preventScroll:true}`). Drop `focusedQKey`/`refocusQ`; keep only the cheap `_qHtml` identical-html skip in `renderDecisions`/`renderPhoneAwaiting`. Clear `ui.qActive` on `session:reset`. | Rewrite plan test 4 as `test_arrow_keys_page_the_active_pager`: `qPagerKey({key:"ArrowRight",…}, {qActive:K, qPage:{}}, fakeNode)` → true, `qPage[K]==1`, preventDefault called; `qActive:null` → false; `key:"j"` → false; `msgmodal.style.display="flex"` → false; `shiftKey:true` → false. Red (export missing / no handler). |
| R5 | Low | `disabled` end arrows: a click on a disabled button is not delivered to the button; inside a timeline card it can fall through to the card's `timeline-entry-open` and open the modal instead of being a no-op. CLI dims the arrow, it does not disable it. | Dim, don't disable. | `aria-disabled="true"` + class `is-dim` on the first/last arrow; the `qpage-step` case clamps via `qPageStep` (no-op at the ends). CSS `.crd-qpager-step.is-dim{opacity:.35}`. Use `←`/`→` glyphs (research §1), not `‹ ›`. Panes get `role="tabpanel"`. | In test 1: prev arrow at index 0 carries `aria-disabled="true"` and no ` disabled`. |
| R6 | Low | CSS `.crd-qpager-tabs{overflow-x:auto;scrollbar-width:none}` hides overflowing tabs invisibly at phone width. | Wrap instead (≤4 tabs, headers ≤12 chars by the tool's own limit). | `.crd-qpager-tabs{display:flex;flex-wrap:wrap;gap:4px;flex:1;min-width:0}`; tab `max-width:14ch;overflow:hidden;text-overflow:ellipsis`. | none (cosmetic; manual check at 390px). |
| R7 | Low | Coverage gaps: the phone card (`renderPhoneAwaiting`) and spine tooltip (`buildMarkers`) paths have no test; plan tests 5 and 8 are guards that are "red" only via a missing export. | Add one assertion per uncovered path; label guards as guards. | Export `renderPhoneAwaiting` (and `buildMarkers` if not already) in `_internal`. | `test_phone_awaiting_pages_multi_q` (fake node whose `.crd-phone-awaiting` records innerHTML → contains `crd-qpager` + all 3 questions); `test_spine_marker_title_counts_more` (`buildMarkers(detail, now, t0, t1)` ask title contains `(+2 more)`). Both red today. |
| R8 | Low | Timeline card goes stale when a decision is answered: repaint is gated on `filtered.length` (`:3548`); open→closed keeps the count, so the card keeps "still open" and no answer until another entry arrives (under talk-only, possibly minutes of tool calls). | Repaint when the number of open asks changes too. MUST NOT repaint every poll. | `renderTimelineEntries`: `var openAsks = filtered.filter(function(e){return e.kind==="ask" && e.decision && e.decision.open;}).length;` add `\|\| openAsks !== ui.timelineOpenAsks` to the `:3548` condition; set `ui.timelineOpenAsks = openAsks` beside `ui.timelineSeen = …` (`:3575`); reset to `-1` in `session:reset` (`:1789`). | Hard to drive in the stub DOM — manual check; no automated test (say so in the commit). |

**Over-engineering cuts (verdict on the research's checklist):** the read-only "Review your answers" page — **cut** (the closed pager panes, the modal stack and the classic panel already show every answer; a fifth pseudo-tab adds state for nothing). multiSelect `[✔]/[ ]` option rows and an `isMulti` field — **cut** (R1's list→string join is the only multiSelect behaviour the tracker needs). Highlighting the chosen option / an "Other" row — **cut** (the answer line shows the typed text as-is). `1/3` position label — keep (one span; useful at phone width where tabs wrap). `qKey` = `t#n` — fine.

**Missed by both plan and research:** R2's tails (the planner only knew about the second prefix); R3 (closed card shows no answer) is a v1 consequence nobody flagged.

## Clean plan (v1 + v2, review folded in)
_Sequenced. v1 is already applied (uncommitted) — keep it. Never `git stash`; revert with scoped Edits. Re-read each region before editing (`sed -n`). Gate commands: `unset TRACKER_AUTH; python3 -m unittest tests.test_cr_timeline tests.test_integration` (confirm the node tests RAN, not skipped), then `unset TRACKER_AUTH; make check` → `selfcheck ok` (Bash timeout ≥ 400000 ms; `Killed: 9` = OOM → rerun per module; one known flaky term_vt backstop)._

**Step 0 — v1 (done; verify only).** `timelineEntryVisible` talk branch includes `ask` (`ext_cr_detail.js:3484`); empty message names questions (`:3510`); `timelineEmptyMessage` exported (`:3763`); v1 tests in `tests/test_cr_timeline.py` (flipped talk-only test, `talkDecisions`, `talkEmpty`). No change.

**Step 1 — tests first (all red except the two guards).**
- `tests/test_integration.py` beside `test_claude_decisions` (`:1227`):
  - `test_claude_multi_question_answers`: tool_use with 2 questions (`"Q1 text"`, `"Q2 text"`) + a user record carrying `toolUseResult={"questions":[…],"answers":{"Q1 text":"A","Q2 text":["x","y"]}}` and result text `Your questions have been answered: "Q1 text"="A", "Q2 text"="x, y". You can now continue with these answers in mind.` → `questions[0]["answer"]=="A"`, `questions[1]["answer"]=="x, y"`, `dec["answer"]` does not end with `in mind.`. A second ask answered with no `toolUseResult` → no `answer` key on its questions (degrade).
  - Extend `test_claude_decisions`: third ask answered `The user answered: "Pick?"="B". Read the answers carefully — they may request clarification, changes, or that you not proceed — and follow what they actually say.` → `answer == '"Pick?"="B"'`.
- `tests/test_cr_timeline.py` — new `_multi_q_detail()` fixture (one OPEN 3-q decision with headers `"Scope"`, `""`, `"DB"`; one CLOSED 2-q decision whose questions carry `answer`; one CLOSED 1-q decision with `answer:"Yes"` and no per-q answer; one Auggie-shaped open 1-q, `header:""`), passed as another `%s` into `_driver_js`:
  1. `test_card_pager_renders_every_question` — `entryHtml(ask3, null, null, {qPage:{}})`: contains `crd-qpager`, all 3 question texts, tab labels `Scope`, `Q2`, `DB`, exactly one `crd-qpager-pane` without `hidden`, prev arrow `aria-disabled="true"` and no ` disabled`.
  2. `test_card_pager_respects_ui_page` — `qPage[qKey(d)]=2` → pane 2 visible, `3/3`; `qPage=9` clamps to pane 2.
  3. `test_qpage_step_clamps` — `(0,-1,3)→0`, `(2,1,3)→2`, `(0,1,3)→1`.
  4. `test_arrow_keys_page_the_active_pager` — per R4 (true/false cases incl. modal open, `qActive:null`, `j`, `shiftKey`).
  5. *Guard (green before and after):* `test_single_question_ask_renders_unchanged` — open 1-q: no `crd-qpager`, has `crd-ask-q` + `crd-ask-pill` + the view-only note.
  6. `test_closed_single_question_card_shows_answer` (R3) — closed 1-q: contains `→` + `Yes`, no `answer in the session`.
  7. `test_decisions_panel_pages_open_and_closed_multi_q` — `renderDecisions(fakeWrap, multiQDetail, {qPage:{}})`: a `crd-qpager` per multi-q decision, every question text, the closed one's per-question `→ A` lines, **no** `Decided:` for the fully-answered closed one.
  8. `test_phone_awaiting_pages_multi_q` (R7) — `renderPhoneAwaiting(fakeNode, multiQDetail, {qPage:{}})` → card HTML has `crd-qpager` + all 3 questions.
  9. `test_spine_marker_title_counts_more` (R7) — `buildMarkers(...)` ask marker title contains `(+2 more)`.
  10. `test_modal_payload_lists_every_question` — 3-q payload contains `1/3`,`2/3`,`3/3` and all questions; closed 2-q payload has `→ A` per question and no `Decided:`; the open 1-q payload equals today's exact string (pin it).
  11. *Guard:* `test_auggie_and_empty_degrade` — Auggie-shaped renders the 1-q markup; `questions:[]` → no throw, no `crd-qpager`; `decisions:[]` panel → empty state.
- Run the gate: expect every new test red except 5 and 11.

**Step 2 — server, `aitracker/providers/claude.py` tool_result branch `:2263-2265`.**
```python
if rid in asks:                                # the user's answer to an AskUserQuestion
    a = re.sub(r"^(?:Your questions have been answered:|The user answered:)\s*", "", rtext)
    a = re.sub(r"\.?\s*(?:You can now continue with these answers in mind\.|Read the answers carefully\b.*)\s*$",
               "", a, flags=re.S)
    asks[rid]["answer"] = a.strip()[:2000]
    asks[rid]["open"] = False
    ans = r_.get("answers") if isinstance(r_, dict) else None   # r_ = this record's toolUseResult (:2169)
    if isinstance(ans, dict):
        by_q = {str(k)[:500]: v for k, v in ans.items()}       # question text is stored [:500] (:2361)
        for q in asks[rid]["questions"]:
            v = by_q.get(q["q"])
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)                 # multiSelect
            if isinstance(v, str) and v:
                q["answer"] = v[:500]
```
Auggie untouched (1 question; UI falls back to `d.answer`). Update the shape comment `ext_cr_detail.js:38` → `questions:[{q,header,options[],answer?}]`. Run the integration tests → green.

**Step 3 — `aitracker/web/ext_cr_detail.js` helpers (ES5 `var`, just above `entryHtml` ~`:3279`), all exported in `_internal` (`~:3747`) with `entryHtml`, `renderPhoneAwaiting`, `buildMarkers` (if missing):**
- `qKey(d)` → `String(d.t || "") + "#" + (d.questions || []).length`.
- `qPageStep(i, dir, n)` → `Math.max(0, Math.min(n - 1, i + dir))`.
- `qAnswer(d, q)` → `q.answer || ""` (per-question only; the whole-decision fallback stays in the callers).
- `questionPagerHtml(d, ctx, ui, optCls, showOpts)` → markup:
  `<div class="crd-qpager" data-qkey="esc(KEY)" role="group" aria-label="N questions">` · head: `<button class="crd-qpager-step[ is-dim]" data-act="qpage-step" data-dir="-1" aria-label="Previous question"[ aria-disabled="true"]>←</button>` · `<div class="crd-qpager-tabs" role="tablist">` one `<button role="tab" class="crd-qpager-tab[ is-cur]" data-act="qpage-go" data-i="i" aria-selected tabindex="0|-1">` + (`qAnswer` or (`!d.open` and no question has its own answer) ? `☒` : `☐`) + `" "` + (`esc(q.header)` or `"Q"+(i+1)`) · `→` step button (dim at n-1) · `<span class="crd-qpager-pos mono">i+1/N</span>` · per question `<div class="crd-qpager-pane" role="tabpanel" data-i="i"[ hidden]>` with `mdHtml(ctx,q.q)` in `crd-qpager-q`, options as `'<div class="' + optCls + '">'` only when `showOpts`, and `<div class="crd-qpager-answer">→ ` + `mdHtml(ctx, ans)` + `</div>` when it has one. Current index = `qPageStep(((ui && ui.qPage) || {})[key] || 0, 0, n)`.
- `applyQPage(pagerEl, i)` → DOM toggle only: `hidden` on panes; `is-cur`/`aria-selected`/`tabindex` on tabs; `is-dim`/`aria-disabled` on the two steps; `.crd-qpager-pos` textContent.
- `goQPage(node, ui, key, i)` → `ui.qPage[key] = i`; `applyQPage` on every `.crd-qpager[data-qkey="key"]` in `node` (card + panel stay in sync).
- `qPagerKey(ev, ui, node)` → per R4; returns true when handled.

**Step 4 — wire the paths (same file).**
- `entryHtml(e, ctx, diagram, ui)`; `renderTimelineEntries` (`:3554`) passes `ui`. Ask branch: n>1 → replace `crd-ask-q`+`crd-ask-opts` with `questionPagerHtml(d, ctx, ui, "crd-ask-pill", true)` (pills for open AND closed, as today); then for n≤1 closed add the R3 answer line `→ (q0.answer || d.answer)`; n>1 closed and not every question answered → same line with `d.answer`. The `crd-ask-note` only when `d.open` (both paths). Mini-head unchanged.
- `renderTimelineEntries` `:3548`/`:3575`/`:1789`: R8 open-ask repaint key.
- `renderDecisions(wrap, session, ui)` (call `:2323` passes `ui`): in `renderQ`, n>1 → `questionPagerHtml(d, null, ui, "crd-decision-opt", isOpen)`; `Decided:` line kept unless every question has its own answer. End: `if (wrap._qHtml !== html) { setPanelBody(wrap, html); wrap._qHtml = html; }` (count/tint above stay unconditional).
- `renderPhoneAwaiting(node, session, ui)` (call `:2324` passes `ui`): n>1 → `questionPagerHtml(d, null, ui, "crd-phone-awaiting-opt", true)` in place of `crd-phone-awaiting-q`+opts; same `_qHtml` skip on `card` (reset `card._qHtml = ""` in the `!open.length` early return).
- `timelineEntryModalPayload` (`:3595`): n>1 → per question `"**" + (i+1) + "/" + n + (header ? " · " + header : "") + "** — " + q.q`, `- option` lines only when `d.open`, `"→ " + answer` when present; footer: `Decided:` only when closed and not every question has its own answer; view-only line when open. n≤1 branch byte-identical.
- `buildMarkers` (`:710`): title `q0.q + (n > 1 ? " (+" + (n - 1) + " more)" : "")`.
- Click delegation (`:1805`): before the switch, set `ui.qActive` per R4; `case "qpage-go"` → `goQPage(node, ui, key, +t.getAttribute("data-i"))` then focus the new current tab (`{preventScroll:true}`, works on Safari); `case "qpage-step"` → `goQPage(node, ui, key, qPageStep(cur, +t.getAttribute("data-dir"), n))` (cur from `ui.qPage[key]||0`, n from the pager's tab count). Both cases `break` before the card's `timeline-entry-open` can fire (the button is the `closest("[data-act]")`).
- `node.addEventListener("focusin", …)` sets `ui.qActive` from `ev.target.closest(".crd-qpager")` when non-null.
- Document keydown `:2146`: first line after the existing three guards → `if (qPagerKey(e, ui, node)) return;`.
- `ui` literal (`:1582`): `qPage: {}, qActive: null, timelineOpenAsks: -1`; `session:reset` (`:1785`): `ui.qPage = {}; ui.qActive = null; ui.timelineOpenAsks = -1;`.

**Step 5 — CSS `aitracker/web/ext_cr_detail.css`** next to `.crd-ask-*` (`~:1635-1642`): `.cr .crd-ask-answer` (copy `.crd-decision-answer` `:1096`); `.crd-qpager-head{display:flex;align-items:center;gap:6px}`; `.crd-qpager-tabs` per R6; `.crd-qpager-tab{white-space:nowrap;max-width:14ch;overflow:hidden;text-overflow:ellipsis;font:inherit;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line-subtle);background:none;color:var(--text-secondary)}`; `.crd-qpager-tab.is-cur{color:var(--text-primary);border-color:currentColor;font-weight:600}`; `.crd-qpager-step{background:none;border:0;color:inherit;font:inherit}` `.crd-qpager-step.is-dim{opacity:.35}`; `.crd-qpager-pos{font-size:10.5px;color:var(--text-muted)}`; `.crd-qpager-answer` = `.crd-decision-answer` look. In the `@media (max-width:600px)` block (`~:1893`): `.crd-qpager-step,.crd-qpager-tab{min-height:44px;min-width:44px}`. Check the gate-misses-CSS memory: no stray `*/`.

**Step 6 — green + red proof.** Gate green. Then revert, one at a time with scoped Edits and re-run the named tests: the `questionPagerHtml` call in `entryHtml` (→ tests 1, 2 red); the `list` join in `claude.py` (→ multi-q integration red); the tail regex (→ `test_claude_decisions` red); the R3 answer line (→ test 6 red); restore each. Restart (`make serve`) and check by hand: a 4-question decision in the card and the panel, click a tab, ←/→ pages, the classic modal's ←/→ still steps entries, terminal input keeps its arrows, 390px width wraps tabs.

**Step 7 — implementation review → `/branch-sync` → push the branch to `personal`; HOLD `/tracker-push`** (contract).

**Risky spots:** `qPagerKey` on the document handler pages a pager the user clicked earlier even after scrolling away (cleared by any click outside a pager, or session switch) — fallback: also require the pager to intersect the viewport. Answer-tail regex is anchored to the two known boilerplates; an unknown future tail just stays visible (today's behaviour).

## Reconciliation (main thread, 2026-11-18)

| # | Finding | Verdict | Note |
|---|---|---|---|
| R1 | multiSelect answers are lists → dropped | confirmed | research §3 shows list answers; join with ", " |
| R2 | only one answer prefix stripped; "The user answered:" + trailing boilerplate leak | confirmed | `claude.py:2264` strips only `Your questions have been answered:`; v1 makes it visible under talk-only |
| R3 | closed ask card shows no answer, always "answer in the session" | confirmed — missed by plan + research | add `→ answer`, keep the note only while open |
| R4 | ←/→ needs focus inside pager (Safari, 2s repaint) | confirmed; review's fix is simpler | `ui.qActive` + existing document keydown (:2146); drop `focusedQKey`/`refocusQ` |
| R5 | disabled end arrows → click falls through to card modal | confirmed (low) | dim, not disable |
| R6 | tab row overflow hidden | confirmed (low) | CSS `flex-wrap` only |
| R7 | phone card / spine tooltip tests are guards only | confirmed (low) | add real red tests |
| R8 | timeline doesn't repaint when open-ask count changes | confirmed (low) | repaint on count change |
| Cuts | Review-your-answers page, [✔] rows, chosen-option highlight, Other row | agreed | overbuilt for a read-only display |
| Missed by both | Auggie has no per-question answers | noted | pager falls back to the single answer line; parity test asserts no throw |

Pending user decisions: D1 R2 cleanup in/out; D2 arrows follow last-clicked pager vs focus-only; D3 answered multi-question → pager vs stacked `· Q → A`.

## User decisions (verbatim, 2026-11-18)

- D1 answer-text cleanup: "1, but make sure that you render it cleanly like how we cleanly render the notes in the config, we did it in a few sessions earlier there"
- D2 arrow keys: "Only while focused"
- D3 answered multi-question: "Same tab pager (Recommended)"
- Sign-off: "Revise first"

## Clean plan v3 (user decisions folded in)
_Author: opus plan agent, 2026-11-18. Grounded by grep + `sed -n` on the worktree (v1 edits uncommitted). Supersedes "Clean plan (v1 + v2, review folded in)" wherever they differ; everything not named in the delta table below is carried over unchanged and restated here so this section is self-contained._

### What "how we render the notes in the Config" is (D1 grounding)
- It is commit **e14694e** "Config + Resume-all confirm panels: readable formatting" (report `reports/confirm-panel-readability.md`). That commit introduced **no JS text formatter** — its JS change is structure only (`ext_cr_dialogs.js` `resumeAllWidget`, `:1446-1466`: list + title/meta rows, note div, `cr-confirm-actions`). The "clean" rendering is a **CSS typographic recipe** in `aitracker/web/ext_cr_dialogs.css`:
  - `:362` `.cr .cr-cfg-row-sub { font: 400 11.5px/1.45 var(--font-sans); color: var(--text-muted); margin-top: 2px }` — every Config row note/description (built by `cfgRow()` `ext_cr_dialogs.js:916`, `line()` `:1438`, status lines). This is "the notes in the config".
  - `:364` `.cr .cr-cfg-row-sub.cr-claude-login-status { color: var(--text-secondary) }` — the precedent for a *modifier* that keeps the note typography but lifts the colour for user-relevant text.
  - `:665-692` `.cr-update-confirm` card, `.cr-resume-all-list/-row/-row-title/-row-meta`, `.cr-resume-all-note` — the confirm-panel card variant.
- **How it is reached from the detail view:** every `ext_*.css` is concatenated in sorted order into one `<style>` by `page.build_page()` (`aitracker/page.py:18,25`): `ext_cr_detail.css` loads **before** `ext_cr_dialogs.css`. Both views live under the `.cr` root (all rules are `.cr .…`), so the class `cr-cfg-row-sub` is directly usable in detail markup. The markdown renderer is the existing `mdHtml(ctx, text)` (`ext_cr_detail.js:197`, wraps app.js's global `md()`). No `window.CR.*` call is needed.
- **Reuse, don't fork:** the answer element carries the Config class itself — `class="crd-answer cr-cfg-row-sub"` — and the only new CSS is a colour/spacing modifier `.cr .cr-cfg-row-sub.crd-answer` (specificity 0,3,0, beats `:362` regardless of file order — the same pattern as `:364`). No second font/size rule for answer text anywhere.
- The other half of "cleanly" is the **text**: after R2's prefix/tail strip the whole-decision answer is still `"Q1"="A", "Q2"="B"` — a quoted blob that repeats the question shown right above it. v3 makes the per-question answer (`"A"`) the thing every view shows, and adds a guarded server-side pair parse so the blob is only the last-resort fallback.

### Delta vs the clean plan (v1 + v2, review folded in)
| Item | Clean plan | v3 | Why |
|---|---|---|---|
| R2 answer cleanup | in | **in** (unchanged regexes) | D1 = "1" |
| Answer rendering | `→ ` + `mdHtml` inline in 3 places, `.crd-ask-answer` / `.crd-qpager-answer` CSS copied from `.crd-decision-answer`, panel fallback `Decided: …` | **one** helper `answerHtml(ctx, text)` → `<div class="crd-answer cr-cfg-row-sub">` on every HTML path; `.crd-ask-answer`, `.crd-qpager-answer` dropped; `Decided:` fallback goes through the same helper | D1: render like the Config notes; no forked formatter |
| Per-question answers when `toolUseResult.answers` is missing | none (degrade to blob) | **new** guarded pair parse `_ask_answer_pairs()` in `claude.py`, accepted only when the pairs re-join to the exact cleaned text | D1 "cleanly": no `"Q"="A"` blob when it is parseable |
| Spine tooltip | `q0 (+n more)` | + ` → answer` for a closed 1-question decision (plain text, via `qAnswer`) | D1 "every path" |
| Classic `app.js` decisions | untouched | per-question `→ answer` line under each stacked question; `decided` footer text only when not every question has its own answer | D1 "every path"; text already cleaned server-side |
| Arrow keys (R4) | `ui.qActive` + document keydown `:2146`, focusin tracking, no refocus | **reverted to v2 focus-gating**: node keydown `:1763` + `focusedQKey`/`refocusQ` around every repaint + `_qHtml` skip; explicit `.focus({preventScroll:true})` on click/tap; `ui.qActive` and the focusin handler **dropped** | D2 = "Only while focused" |
| Test 4 | `test_arrow_keys_page_the_active_pager` (qActive) | `test_arrow_keys_page_only_when_focus_in_pager` | D2 |
| Closed multi-q in Decisions panel | pager, options hidden (`showOpts = isOpen`) | pager, **options shown** (`showOpts = true`) + per-page `→ answer` | D3: "each page: question, options, → answer" |
| Modal payload | stacked `i/N` blocks | unchanged (stacked) — the modal is a markdown text pop-out whose ←/→ belong to `app.js:2886` `navModal`; a pager there would collide | D3 applies to the in-page views |
| R1, R3, R5, R6, R7, R8, cuts | as reconciled | unchanged | — |

### Step 0 — v1 (done; verify only)
`timelineEntryVisible` talk branch includes `ask` (`ext_cr_detail.js` ~`:3484`); empty message names questions (~`:3510`); `timelineEmptyMessage` exported (`:3763`); v1 tests in `tests/test_cr_timeline.py` (flipped talk-only test, `talkDecisions`, `talkEmpty`). No change.

### Step 1 — tests first (each red on the current worktree except the labelled guards)
`tests/test_integration.py`, beside `test_claude_decisions` (`:1227`):
- **I1 `test_claude_multi_question_answers`** (R1): tool_use with 2 questions `"Q1 text"`, `"Q2 text"`; user record `toolUseResult={"questions":[…],"answers":{"Q1 text":"A","Q2 text":["x","y"]}}`, result text `Your questions have been answered: "Q1 text"="A", "Q2 text"="x, y". You can now continue with these answers in mind.` → `questions[0]["answer"]=="A"`, `questions[1]["answer"]=="x, y"`, `dec["answer"]` does not end with `in mind.` Red: list answers dropped today, no per-q answers at all.
- **I2 extend `test_claude_decisions`** (R2): third ask answered `The user answered: "Pick?"="B". Read the answers carefully — they may request clarification, changes, or that you not proceed — and follow what they actually say.` → `answer == '"Pick?"="B"'`; and the existing `Your questions…` case no longer ends with `in mind.` Red today.
- **I3 `test_claude_answer_pairs_fallback`** (v3-new): 2-q ask, **no** `toolUseResult`, text `Your questions have been answered: "Q1 text"="A", "Q2 text"="B". You can now continue with these answers in mind.` → per-q answers `A`, `B`. Same with an embedded quote that breaks re-join (`"Q1 text"="say "hi"", "Q2 text"="B"`) → **no** `answer` key on either question (all-or-nothing), `dec["answer"]` still set. Unparseable text (`User declined to answer questions`) → no per-q answers. Red today (no parse).

`tests/test_cr_timeline.py` — new `_multi_q_detail()` fixture passed as another `%s` into `_driver_js` (`:185`): one OPEN 3-q decision (headers `"Scope"`, `""`, `"DB"`); one CLOSED 2-q decision whose questions carry `answer` (`"A"`, `"B"`) and `d.answer='"Q1"="A", "Q2"="B"'`; one CLOSED 1-q decision with `q0.answer:"Yes"`, `d.answer:'"Ship?"="Yes"'`; one CLOSED 1-q decision with only `d.answer:"User responded: ok"` (Auggie-shaped, `header:""`, no per-q answer); one Auggie-shaped OPEN 1-q.
1. `test_card_pager_renders_every_question` — `entryHtml(ask3, null, null, {qPage:{}})`: `crd-qpager`, all 3 texts, tab labels `Scope`, `Q2`, `DB`, exactly one pane without `hidden`, prev arrow `aria-disabled="true"` and no ` disabled`, the pager carries `tabindex="-1"`.
2. `test_card_pager_respects_ui_page` — `qPage[qKey(d)]=2` → pane 2 visible, `3/3`; `qPage=9` clamps to pane 2.
3. `test_qpage_step_clamps` — `(0,-1,3)→0`, `(2,1,3)→2`, `(0,1,3)→1`.
4. **`test_arrow_keys_page_only_when_focus_in_pager`** (v3, D2) — `qPagerOnKey(ev, ui, node)` with a fake pager element (`closest(".crd-qpager")` returns it, `getAttribute("data-qkey")` = K, 3 tabs): `{key:"ArrowRight", target:<inside pager>}` → true, `ui.qPage[K]==1`, `preventDefault` called; same key with a target whose `closest` returns null (focus outside any pager, e.g. `document.body`) → false and `qPage` untouched; `key:"j"` → false; `shiftKey`/`metaKey`/`ctrlKey`/`altKey` → false; `#msgmodal` `style.display="flex"` → false. Red: export missing.
5. *Guard (green before and after):* `test_single_question_ask_renders_unchanged` — open 1-q: no `crd-qpager`, has `crd-ask-q` + `crd-ask-pill` + the view-only note.
6. `test_closed_single_question_card_shows_answer` (R3 + D1) — closed 1-q: contains `class="crd-answer cr-cfg-row-sub"`, `→`, `Yes`; **not** `&quot;Ship?&quot;` (the per-q answer wins over the blob); no `answer in the session`. Auggie-shaped closed 1-q → answer line shows `User responded: ok`. Red today.
7. `test_decisions_panel_pages_open_and_closed_multi_q` (D3) — `renderDecisions(fakeWrap, multiQDetail, {qPage:{}})`: a `crd-qpager` per multi-q decision, every question text, the closed 2-q decision's panes show **options** (`crd-decision-opt`) and a `crd-answer cr-cfg-row-sub` line per answered question; no `"Q1"="A"` blob and no `Decided:` for the fully-answered closed one.
8. `test_phone_awaiting_pages_multi_q` (R7) — `renderPhoneAwaiting(fakeNode, multiQDetail, {qPage:{}})` → `crd-qpager` + all 3 questions.
9. `test_spine_marker_title_counts_more` (R7 + D1) — `buildMarkers(...)`: open 3-q ask title contains `(+2 more)`; closed 1-q title contains `→ Yes`.
10. `test_modal_payload_lists_every_question` — 3-q payload contains `1/3`,`2/3`,`3/3` and all questions; closed 2-q payload has `→ A`, `→ B` and no `Decided:`; the open 1-q payload equals today's exact string (pin it).
11. *Guard:* `test_auggie_and_empty_degrade` — Auggie-shaped renders the 1-q markup; `questions:[]` → no throw, no `crd-qpager`; `decisions:[]` panel → empty state.
12. **`test_answer_html_uses_config_note_class`** (v3-new, D1) — `answerHtml(null, "**x**")` → starts `<div class="crd-answer cr-cfg-row-sub">`, contains `→` and `<strong>x</strong>` (went through `mdHtml`); `answerHtml(null, "")` → `""`. Plus a Python-side CSS check in the same file: `ext_cr_dialogs.css` still has the `.cr .cr-cfg-row-sub {` rule with `11.5px`; `ext_cr_detail.css` has a `.cr .cr-cfg-row-sub.crd-answer` rule whose body contains **no** `font` declaration (typography stays the Config note's — no fork); and `ext_cr_detail.js` contains no `crd-decision-answer`, `crd-ask-answer` or `crd-qpager-answer` (every path uses the helper). Red: helper missing.
13. **`test_every_answer_path_uses_answer_html`** (v3-new, D1) — count `class="crd-answer cr-cfg-row-sub"` in `entryHtml(closed2q)` with `qPage` stepped to each page (the answer of each page appears), in `renderDecisions` output (= 3 answered questions + 1 Auggie fallback), and assert zero occurrences of `Your questions have been answered`, `You can now continue`, `Read the answers carefully` across all rendered HTML for a fixture whose `d.answer` was produced by I2's server cleanup (copy the cleaned string literally). Red today.
- Classic view: `tests/test_cr_timeline.py` cannot drive `app.js`'s `render`; add **C1** a source-level assertion in the same file: `app.js` decisions block (grep the `const qs=(x.questions||[]).map(` line ± 6) contains `q.answer` (per-question answer rendered). Red today.
- Run the gate: expect every new test red except 5 and 11.

### Step 2 — server, `aitracker/providers/claude.py` tool_result branch (`:2263-2265`)
```python
_ASK_PAIR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"')   # module level, beside the other _RE constants

def _ask_answer_pairs(text):
    """'"Q1"="A", "Q2"="B"' -> {"Q1": "A", "Q2": "B"}; {} unless the pairs re-join to the exact text."""
    pairs = _ASK_PAIR_RE.findall(text or "")
    if not pairs or ", ".join('"%s"="%s"' % p for p in pairs) != text:
        return {}
    return {q[:500]: a for q, a in pairs}

# in the tool_result branch:
if rid in asks:                                # the user's answer to an AskUserQuestion
    a = re.sub(r"^(?:Your questions have been answered:|The user answered:)\s*", "", rtext)
    a = re.sub(r"\.?\s*(?:You can now continue with these answers in mind\.|Read the answers carefully\b.*)\s*$",
               "", a, flags=re.S).strip()
    asks[rid]["answer"] = a[:2000]
    asks[rid]["open"] = False
    ans = r_.get("answers") if isinstance(r_, dict) else None   # r_ = this record's toolUseResult (:2169)
    by_q = ({str(k)[:500]: v for k, v in ans.items()} if isinstance(ans, dict)
            else _ask_answer_pairs(a))                         # v3: text fallback, all-or-nothing
    for q in asks[rid]["questions"]:
        v = by_q.get(q["q"])
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)                     # multiSelect (R1)
        if isinstance(v, str) and v:
            q["answer"] = v[:500]
```
Auggie untouched (its `User responded:` path stays; UI falls back to `d.answer` for a 1-question decision). Update the shape comment `ext_cr_detail.js:38` → `questions:[{q,header,options[],answer?}]`. Run I1–I3 → green.

### Step 3 — `aitracker/web/ext_cr_detail.js` helpers (ES5 `var`, just above `entryHtml` `:3279`; all exported in `_internal` `:3747` together with `entryHtml`, `renderDecisions`, `renderPhoneAwaiting`, `buildMarkers` if missing)
- `qKey(d)` → `String(d.t || "") + "#" + (d.questions || []).length`.
- `qPageStep(i, dir, n)` → `Math.max(0, Math.min(n - 1, i + dir))`.
- `qAnswer(d, q, n)` → `q.answer || (n <= 1 && !d.open ? (d.answer || "") : "")` — per-question first; the whole-decision text only for a 1-question decision. (v3: the single fallback rule, used by every path.)
- **`answerHtml(ctx, text)`** (v3, D1) → `text ? '<div class="crd-answer cr-cfg-row-sub"><span class="crd-answer-arrow" aria-hidden="true">→</span> ' + mdHtml(ctx, text) + "</div>" : ""`. The **only** place answer HTML is built.
- `questionPagerHtml(d, ctx, ui, optCls, showOpts)` → `<div class="crd-qpager" data-qkey="esc(KEY)" tabindex="-1" role="group" aria-label="N questions">` · head: `<button type="button" class="crd-qpager-step[ is-dim]" data-act="qpage-step" data-dir="-1" aria-label="Previous question"[ aria-disabled="true"]>←</button>` · `<div class="crd-qpager-tabs" role="tablist">` one `<button type="button" role="tab" class="crd-qpager-tab[ is-cur]" data-act="qpage-go" data-i="i" aria-selected="true|false" tabindex="0|-1">` + (`qAnswer(d,q,n)` ? `☒` : `☐`) + `" "` + (`esc(q.header)` or `"Q"+(i+1)`) · `→` step (dim at n-1) · `<span class="crd-qpager-pos mono">i+1/N</span>` · per question `<div class="crd-qpager-pane" role="tabpanel" data-i="i"[ hidden]>` = `<div class="crd-qpager-q">` + `mdHtml(ctx,q.q)` + `</div>` + options (`'<div class="' + optCls + '">' + mdHtml(ctx,o) + '</div>'`, only when `showOpts`) + `answerHtml(ctx, qAnswer(d, q, n))`. Current index = `qPageStep(((ui && ui.qPage) || {})[key] || 0, 0, n)`.
- `applyQPage(pagerEl, i)` → DOM only: `hidden` on panes; `is-cur`/`aria-selected`/`tabindex` on tabs; `is-dim`/`aria-disabled` on the steps; `.crd-qpager-pos` text.
- `goQPage(node, ui, key, i)` → `ui.qPage[key] = i`; `applyQPage` on every `.crd-qpager` in `node` whose `getAttribute("data-qkey") === key` (loop + compare — no selector escaping of ISO timestamps).
- `focusFirstCur(pg)` → `var t = pg.querySelector(".crd-qpager-tab.is-cur"); (t || pg).focus({ preventScroll: true })` (try/catch → `focus()` for old engines).
- **`qPagerOnKey(ev, ui, node)`** (v3, D2) → return false unless: `ev.key` is `ArrowLeft`/`ArrowRight`; no `shiftKey/metaKey/ctrlKey/altKey`; `#msgmodal` and `#diffmodal` not displayed (`app.js:2886` owns ←/→ there); `var pg = ev.target && ev.target.closest && ev.target.closest(".crd-qpager")` non-null and `node.contains(pg)`. Then: `n` = tab count, `cur = ui.qPage[key] || 0`, `goQPage(node, ui, key, qPageStep(cur, ev.key === "ArrowRight" ? 1 : -1, n))`; if `ev.target` is a tab → `focusFirstCur(pg)` (roving focus, ARIA tabs); `ev.preventDefault()`; return true. Focus is the gate — no `ui.qActive`.
- **`focusedQKey(container)`** (v3, D2, restored from v2) → `var a = document.activeElement; var pg = a && container.contains(a) && a.closest && a.closest(".crd-qpager"); return pg ? { key: pg.getAttribute("data-qkey"), onTab: a.classList.contains("crd-qpager-tab") } : null`.
- **`refocusQ(container, f)`** → if `f`: find the pager in `container` with that `data-qkey` (loop + compare); `f.onTab ? focusFirstCur(pg) : pg.focus({preventScroll:true})`. No-op when the pager is gone (decision vanished/filtered).

### Step 4 — wire the paths (same file)
- **Timeline card** `entryHtml(e, ctx, diagram, ui)`; `renderTimelineEntries` (`:3514`, map at `:3554`) passes `ui`. Ask branch (`~:3318-3334`): n>1 → replace `crd-ask-q`+`crd-ask-opts` with `questionPagerHtml(d, ctx, ui, "crd-ask-pill", true)`; n>1 closed and **no** question has its own answer → also `answerHtml(ctx, d.answer)` under the pager (blob fallback). n≤1 closed → `answerHtml(ctx, qAnswer(d, q0, 1))` after the question (R3). `crd-ask-note` only when `d.open` (both paths). Open 1-q markup byte-identical. Mini-head unchanged.
- **Timeline repaint** `:3548-3556`: condition gains `|| openAsks !== ui.timelineOpenAsks` (R8; `openAsks` = open ask count of `filtered`; `ui.timelineOpenAsks = openAsks` beside `:3575`). Wrap the `innerHTML` write: `var fq = focusedQKey(scrollEl);` before, `refocusQ(scrollEl, fq);` after (D2).
- **Decisions panel** `renderDecisions(wrap, session, ui)` (`:2784`; call `:2323` passes `ui`): in `renderQ`, n>1 → `questionPagerHtml(d, null, ui, "crd-decision-opt", true)` (v3/D3: options on open **and** closed pages) in place of `crd-decision-q` + opts; n>1 closed with no per-q answer → `answerHtml(null, d.answer)` under it. n≤1: unchanged question/options; the `Decided: …` line (`:2796`) becomes `answerHtml(null, qAnswer(d, q0, 1))` for closed. End of function: `if (wrap._qHtml !== html) { var fq = focusedQKey(wrap); setPanelBody(wrap, html); wrap._qHtml = html; refocusQ(wrap, fq); }` (count/tint above stay unconditional).
- **Phone card** `renderPhoneAwaiting(node, session, ui)` (`:1170`; call `:2324` passes `ui`): open decisions only, so no answers; n>1 → `questionPagerHtml(d, null, ui, "crd-phone-awaiting-opt", true)` in place of `crd-phone-awaiting-q`+opts; same `_qHtml` skip + `focusedQKey`/`refocusQ` on `card`; reset `card._qHtml = ""` in the `!open.length` early return (`:1174`).
- **Modal payload** `timelineEntryModalPayload` (`:3591`): n>1 → per question `"**" + (i+1) + "/" + n + (header ? " · " + header : "") + "** — " + q.q`, `- option` lines when `d.open`, `"→ " + qAnswer(d, q, n)` when non-empty; footer `→ ` + `d.answer` only when closed and no question has its own answer; view-only line when open. n≤1 open: byte-identical. n≤1 closed: `:3601`'s `**Decided:** ` + d.answer → `"\n→ " + qAnswer(d, q0, 1)` (same text as the card). This payload is markdown for app.js's msgmodal — the answer *text* is the cleaned one; no HTML helper applies there.
- **Spine** `buildMarkers` (`:710-711`): title = `q0.q + (n > 1 ? " (+" + (n - 1) + " more)" : "") + (n <= 1 && !d.open && qAnswer(d, q0, 1) ? " → " + qAnswer(d, q0, 1) : "") + " · " + fmtClock(t)` — plain text in a `title` attribute.
- **Click delegation** (`:1805`), before the switch: `var pg = ev.target.closest && ev.target.closest(".crd-qpager"); if (pg && !pg.contains(document.activeElement)) pg.focus({ preventScroll: true });` (D2 + Safari: a click on a `<button>` or on pane text does not focus in WebKit — this does it explicitly). `case "qpage-go"` → `goQPage(node, ui, key, +t.getAttribute("data-i")); focusFirstCur(pg); break;` · `case "qpage-step"` → `goQPage(node, ui, key, qPageStep(ui.qPage[key] || 0, +t.getAttribute("data-dir"), n)); focusFirstCur(pg); break;` (`key` from `pg`, `n` = pg's tab count). Both `break` before the card's `timeline-entry-open` (the button is `closest("[data-act]")`). A click on pane text inside a timeline card still opens the entry modal as today (focus then moves to the modal, and ←/→ belong to `navModal`).
- **Keydown**: first line of the existing `node.addEventListener("keydown", …)` (`:1763`): `if (qPagerOnKey(ev, ui, node)) return;`. Node-level, so it fires only while focus is inside the detail view; `qPagerOnKey` further requires focus inside a pager. The document handler `:2146` is **not** touched.
- **State**: `ui` literal (`~:1582-1585`): `qPage: {}, timelineOpenAsks: -1`; `session:reset` (`:1784-1789`): `ui.qPage = {}; ui.timelineOpenAsks = -1;`. **No `qActive`, no `focusin` listener.**

### Step 4b — classic `aitracker/web/app.js` decisions (`:2166-2174`)
Not under `.cr`, renders with the global `md()`; the cleaned server text already fixes its blob. Smallest change: in the `qs` map append `(q.answer ? \`<div class=decqa>→ ${md(q.answer)}</div>\` : "")` after each question's options; the closed footer shows `md(x.answer)` only when not every question has `q.answer` (else just `✔ decided`). CSS `aitracker/app.css`: `.decqa{font-size:12px;color:var(--…secondary token used by .decans…);margin-top:2px}` — copy the token `.decans` already uses (grep it; do not invent one). Classic cannot reach `answerHtml` (it is inside the ext IIFE and loads after app.js); this is classic's own renderer family, not a fork of the CR one.

### Step 5 — CSS `aitracker/web/ext_cr_detail.css`
- Next to `.crd-decision-answer` (`:1096`, now unused → delete the rule): `.cr .cr-cfg-row-sub.crd-answer { color: var(--text-secondary); margin-top: 4px; }` and `.cr .crd-answer-arrow { color: var(--text-muted); }`. **No font declaration** — size/line-height/family come from `.cr .cr-cfg-row-sub` (`ext_cr_dialogs.css:362`). Inside `.crd-ask-*` cards the inherited 14px `.crd-ask-q` does not apply (the answer is a sibling div), so the 11.5px note typography holds.
- Pager (unchanged from clean plan, R5/R6): `.crd-qpager:focus{outline:none}` `.crd-qpager:focus-visible{outline:2px solid var(--line-default);outline-offset:2px}`; `.crd-qpager-head{display:flex;align-items:center;gap:6px}`; `.crd-qpager-tabs{display:flex;flex-wrap:wrap;gap:4px;flex:1;min-width:0}`; `.crd-qpager-tab{white-space:nowrap;max-width:14ch;overflow:hidden;text-overflow:ellipsis;font:inherit;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line-subtle);background:none;color:var(--text-secondary)}`; `.crd-qpager-tab.is-cur{color:var(--text-primary);border-color:currentColor;font-weight:600}`; `.crd-qpager-step{background:none;border:0;color:inherit;font:inherit}` `.crd-qpager-step.is-dim{opacity:.35}`; `.crd-qpager-pos{font-size:10.5px;color:var(--text-muted)}`. In the `@media (max-width:600px)` block (`~:1893`): `.crd-qpager-step,.crd-qpager-tab{min-height:44px;min-width:44px}`. No stray `*/` (memory: gate misses CSS load errors).

### Step 6 — gate, red proof, manual
- Gate: `unset TRACKER_AUTH; python3 -m unittest tests.test_cr_timeline tests.test_integration` (confirm the node tests RAN — no `skipped` on the `_HAS_NODE` cases), then `unset TRACKER_AUTH; make check` → `selfcheck ok` (Bash timeout ≥ 400000 ms; `Killed: 9` = OOM → rerun per module; one known flaky term_vt backstop).
- Red proof, one at a time with scoped Edits (never `git stash`), re-run the named tests, restore: `questionPagerHtml` call in `entryHtml` (→ 1, 2); `list` join (→ I1); tail regex (→ I2); `_ask_answer_pairs` fallback (→ I3); `answerHtml`'s `cr-cfg-row-sub` class (→ 12, 13); `qPagerOnKey`'s `closest(".crd-qpager")` focus gate (→ 4's outside-pager case); R3 answer line (→ 6).
- Restart (`make serve`, UI change) and check by hand: 4-question decision in card and panel; click a tab in Safari **and** Chrome, then ←/→ pages; click outside → ←/→ do nothing (D2); wait ≥ 4 s (two polls) with focus on a tab → ←/→ still work (repaint survival); classic modal ←/→ still steps entries; terminal input keeps its arrows; 390 px width wraps tabs; an answered decision's `→ answer` reads in Config-note typography, no `"Q"="A"` / `You can now continue…` text anywhere.

### Step 7 — implementation review (opus) → `/branch-sync` → push the branch to `personal`; **HOLD `/tracker-push`** (contract).

### Risky spots + fallback
1. **Focus survival across repaints (D2).** The 2 s poll rebuilds the panel/card/timeline via `innerHTML`; any path that writes without `focusedQKey`/`refocusQ` silently drops focus and ←/→ "stop working". Mitigation: the `_qHtml` skip means identical polls never repaint; the three repaint sites are the only writers of pager markup (grep `questionPagerHtml` callers in review). Fallback if a browser still loses focus: keep the focus gate but also accept the pager under `:hover` (`pg.matches(":hover")`) — still no global `qActive`.
2. **`refocusQ` stealing focus.** It only fires when focus was inside a pager in that same container before the write, and uses `preventScroll`, so it cannot pull focus from a terminal or input.
3. **Pair-parse false fill (D1).** All-or-nothing exact re-join; any embedded quote, unknown separator or extra text → `{}` → blob fallback (today's behaviour, cleaned). Unknown future boilerplate tails stay visible.
4. **Class reuse coupling.** If someone later restyles `.cr-cfg-row-sub` for Config, answers follow — that is the point (one recipe), and test 12 pins that the detail CSS adds no font rule.

### Decisions the user may overrule
- Pager-wide click focus: clicking pane text inside a **timeline card** still opens the entry modal (today's behaviour); only tab/arrow buttons page without opening it. Alternative: make pane clicks inside a pager not open the modal.
- `answerHtml` uses the Config note's muted-family typography with `--text-secondary` colour (like the Claude-login status row). Alternative: keep it fully muted exactly like a Config note.

## Plan v3 re-review (opus)
_Reviewer: opus, 2026-11-18. Method: grep + `sed -n` on the worktree; a read-only scan of 600 real `~/.claude/projects/**/*.jsonl` transcripts containing AskUserQuestion (only prefixes, suffixes, key shapes and counts were looked at)._

**Verified sound (no change):**
- **D1 CSS reach.** `#nextRoot` is `class="tracker-next cr"` (`index.html:230`), so detail markup sits under `.cr`. `page.build_page()` (`page.py:16-17,25`) joins `ext_*.css` in sorted order: `ext_cr_detail.css` loads before `ext_cr_dialogs.css`. `.cr .cr-cfg-row-sub.crd-answer` has specificity 0,3,0 and beats `:362` (0,2,0) whatever the order. This is the same pattern as `:364`.
- **mdHtml is XSS-safe on answer text.** `md()` escapes `&<>` before any markdown runs (`app.js:192,196`). An href can only be `https?://` and never contains `"`. The spine tooltip goes through the detail's own `esc` (`ext_cr_detail.js:89`), which also escapes `"`/`'`. That is the same exposure as the question text `mdHtml` already renders.
- **R2 regexes match real data.** Answered results use exactly two prefix/tail pairs: 160× `Your questions have been answered:` … `. You can now continue with these answers in mind.` and 158× `The user answered:` … `. Read the answers carefully — … follow what they actually say.` v3's two regexes strip both.
- **D2 focus gating.** The only ←/→ handlers are `app.js:2886-2891` (gated on `#msgmodal`/`#diffmodal` display) and `ext_vt.js:284-285` (inside the terminal). The node-level listener (`:1763`) fires before the document listeners. With the `#msgmodal`/`#diffmodal` guard, an open modal keeps `navModal`. The j/k handler at `:2146` is unchanged; it already fires on any focus that is not an input. Pager markup has exactly three writers: `renderTimelineEntries :3553` (covers callers `:1976`, `:3266`, `:3418`), `setPanelBody` via `renderDecisions`, and `renderPhoneAwaiting`. The degraded write at `:3257` removes the pager, so nothing needs refocusing there. Safari: clicking a `<button>` does not focus it, and v3's explicit `.focus({preventScroll:true})` in the delegated click handler covers that. A `tabindex="-1"` div can be focused programmatically in WebKit.
- **D3.** The pager runs on every in-page path, and the modal stays stacked. Keeping the modal stacked is right: `navModal` owns ←/→ in it (`app.js:2889-2890`).

| # | Sev | Finding (defect · repro) | Fix direction (what changes / what must NOT) | Way | Test (red before) |
|---|---|---|---|---|---|
| F1 | Med (cut) | **The `"Q"="A"` pair parse is dead code, and it fails on real text.** All 318 of 318 real answered `type:"user"` records carry a `toolUseResult.answers` dict. The only records without one are 83 `api-request-blob` duplicates. Those pass through the same tool_result branch, because the detail loop `claude.py:2148-2162` does not skip `_BLOB_TYPES`; the skip at `:1854` is in another function. They arrive after the real record, which has already set every answer. The regex also rejects 74 of 319 real texts (23%), because question text contains literal `"`. | Remove `_ASK_PAIR_RE`, `_ask_answer_pairs` and test I3. `by_q` comes from the answers dict only. A blob record must never clear a per-question answer, and the loop already guarantees that because it only sets values. | `claude.py` ask branch: `by_q = {str(k)[:500]: v for k, v in ans.items()} if isinstance(ans, dict) else {}` | None (cut I3). I1/I2 stay. |
| F2 | Med | **Declined, interrupted and errored asks show tool boilerplate as the "answer".** 16 of 335 results (about 5%) are `is_error:true`, for example `The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, …) STOP what you are doing…` (436–1221 chars), `[Tool call interrupted: …]` or `<tool_use_error>InputValidationError…`. v3's R3 now prints this as `→ …` on the timeline card (talk-only), the spine tooltip, the panel and the modal. Expected: a short, clean outcome. | Server side only, and only when `b.get("is_error")`: answer = `Declined`, plus ` — <msg>` when the text has `the user said:` (msg = the text after it, up to the first blank line). Any other is_error → `No answer recorded`. The non-error path must not change. Per-question answers are never set on an error. | `claude.py:2263` branch: check `is_error` before the R2 regexes (see v4 Step 2). | **I4** `test_claude_declined_ask_is_clean`: is_error rejection → `answer == "Declined"`, `open False`. Rejection with `…the user said:\nclarify first\n\nNote: …` → `"Declined — clarify first"`. Interrupted → `"No answer recorded"`. Red today (raw text stored). |
| F3 | Low | **The user's per-answer notes are dropped.** `toolUseResult.annotations[q].notes` (the user's typed note, 1 of 319) is visible today inside the blob in the panel's `Decided:`. v3 shows only `answers[q]`, so the note disappears. | Append the note to that question's answer. Previews (`annotations[q].preview`, assistant-authored) stay out. | In the `by_q` loop: `n = ((ann or {}).get(q["q"]) or {}).get("notes")`, then `if isinstance(n, str) and n.strip(): v = v + " — notes: " + n.strip()[:300]` | Extend I1: a `toolUseResult.annotations` entry `{"Q1 text": {"notes": "only on staging"}}` → `questions[0]["answer"] == "A — notes: only on staging"`. Red today. |
| F4 | Low (test) | **Test 6's negative check can never fail.** `md()` uses app.js's `esc`, which does not escape `"` (`app.js:192`), so `&quot;Ship?&quot;` never appears. An implementation that renders the blob (`→ "Ship?"="Yes"`) still passes. Test 7's "no blob" check has the same risk if it is written escaped. | Assert the exact rendered fragment and the raw blob's absence. | Test 6: `assertIn('</span> Yes</div>', html)` and `assertNotIn('"Ship?"=', html)`. Test 7: `assertNotIn('"Q1"="A"', html)` (raw). | Red-proof: make `qAnswer` return `d.answer` first → 6 and 7 go red. |
| F5 | Low (test gap) | **Focus restore across repaints (v3 risky spot 1) has no automated test.** The manual step is the only check. | Add a unit test for `focusedQKey` and `refocusQ`. Keep the manual 2-poll check. | Export both in `_internal`. | **4b** `test_refocus_restores_pager_focus`: set `document.activeElement` to a fake tab (classList contains `crd-qpager-tab`, `closest` → pager with key K) inside a fake container. Assert `focusedQKey` → `{key:K,onTab:true}`. `refocusQ(newContainer, f)` → the `.is-cur` tab's `focus` spy is called with `{preventScroll:true}`. When no pager with K exists, there is no call and no throw. Red: exports missing. Red-proof: drop the `onTab` branch. |
| F6 | Low (overbuilt) | **Step 4b (classic `app.js` per-question answers) and C1 are outside the contract**, which covers Control Room's narration tab and its pager. Classic already shows the cleaned text once R2 lands server-side (`app.js:2174` `md(x.answer)`). C1 only greps the source. | Cut Step 4b, the `.decqa` CSS and C1. Classic stays untouched. | — | — |
| F7 | Low | **Inline `code` inside an answer is unstyled.** The code-span selector list `ext_cr_detail.css:1490-1494` covers `.crd-ask-q`/`.crd-ask-pill` but not the answer. | Add one selector to the existing list. Do not add a second rule. | Add `.cr .crd-answer code,` to that list. | Extend test 12's CSS check: `.cr .crd-answer code` appears in `ext_cr_detail.css`. |
| F8 | Info | The "Auggie-shaped" fixtures use `d.answer:"User responded: ok"`, but `auggie.py:598` strips that prefix, so real Auggie answers read `ok`. | Use `"ok"` in the fixtures. | Fixture only. | — |
| F9 | Info | In the Decisions panel, a closed one-question decision hides its options (`:2800` `isOpen ? opts : ""`), while v3's closed multi-question pages show them. The D3 wording ("each page: question, options, → answer") is not recorded verbatim in this file. | No change. Accepted, because it follows the D3 option the user picked. | — | — |
| F10 | Info | The test 13 phrase-absence checks run on a fixture that is already clean, so they cannot go red. The count check carries the test. | Keep. Do not count those checks as red-proof. | — | — |

**Verdict: v3 does not stand. Clean plan v4 below supersedes it** (F1 cut, F2/F3 added, F4/F5/F7 test fixes, F6 cut). No new user decision is needed. Two points can be overruled: F6 (classic view cut) and F2's wording (`Declined` / `No answer recorded`).

## Clean plan v4 (supersedes v3; self-contained for a sonnet implementer)
_Everything not mentioned here is cut. Line numbers are from the worktree at the time of review. Re-read each region right before editing (conventions rule 12)._

### Step 0 — v1 (done; verify only)
The `timelineEntryVisible` talk branch includes `ask` (`ext_cr_detail.js` ~`:3484`). The empty message names questions (~`:3510`). `timelineEmptyMessage` is exported (`:3763`). The v1 tests in `tests/test_cr_timeline.py` exist (flipped talk-only test, `talkDecisions`, `talkEmpty`). No change.

### Step 1 — tests first (every test red on the current worktree except the labelled guards)
`tests/test_integration.py`, beside `test_claude_decisions` (`:1227`):
- **I1 `test_claude_multi_question_answers`**: a tool_use with 2 questions, `"Q1 text"` and `"Q2 text"`. The user record has `toolUseResult={"questions":[…],"answers":{"Q1 text":"A","Q2 text":["x","y"]},"annotations":{"Q1 text":{"notes":"only on staging","preview":"P"}}}` and result text `Your questions have been answered: "Q1 text"="A", "Q2 text"="x, y". You can now continue with these answers in mind.` Expect `questions[0]["answer"] == "A — notes: only on staging"`, `questions[1]["answer"] == "x, y"`, and `dec["answer"]` not ending with `in mind.`
- **I2 extend `test_claude_decisions`**: a third ask answered with `The user answered: "Pick?"="B". Read the answers carefully — they may request clarification, changes, or that you not proceed — and follow what they actually say.` Expect `answer == '"Pick?"="B"'`. The existing `Your questions…` case no longer ends with `in mind.`
- **I4 `test_claude_declined_ask_is_clean`**: three asks, each closed by an `is_error: true` tool_result:
  - `The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to the file). STOP what you are doing and wait for the user to tell you how to proceed.` → `"Declined"`
  - the same text plus ` To tell you how to proceed, the user said:\nclarify first\n\nNote: The user's next message may contain a correction.` → `"Declined — clarify first"`
  - `[Tool call interrupted: the session ended before this call's result was recorded, so its outcome is unknown.]` → `"No answer recorded"`

  All three are `open False`, and none of their questions has an `answer` key.

`tests/test_cr_timeline.py`: add a new `_multi_q_detail()` fixture, passed as another `%s` into `_driver_js` (`:185`). It holds:
- an OPEN 3-question decision with headers `"Scope"`, `""`, `"DB"`
- a CLOSED 2-question decision whose questions carry `answer` (`"A"`, `"B"`), with `d.answer='"Q1"="A", "Q2"="B"'`
- a CLOSED 1-question decision with `q0.answer:"Yes"` and `d.answer:'"Ship?"="Yes"'`
- a CLOSED Auggie-shaped 1-question decision (`header:""`, no per-question answer, `d.answer:"ok"`)
- an Auggie-shaped OPEN 1-question decision

Export from `_internal` (`:3747`), together with `entryHtml`, `renderDecisions`, `renderPhoneAwaiting` and `buildMarkers` where missing: `qKey`, `qPageStep`, `qAnswer`, `answerHtml`, `questionPagerHtml`, `qPagerOnKey`, `focusedQKey`, `refocusQ`.

1. `test_card_pager_renders_every_question`: `entryHtml(ask3, null, null, {qPage:{}})` contains `crd-qpager`, all 3 question texts and the tab labels `Scope`, `Q2`, `DB`. Exactly one pane lacks `hidden`. The prev arrow has `aria-disabled="true"` and no ` disabled`. The pager carries `tabindex="-1"`.
2. `test_card_pager_respects_ui_page`: with `qPage[qKey(d)]=2`, pane 2 is visible and the counter reads `3/3`. `qPage=9` clamps to pane 2.
3. `test_qpage_step_clamps`: `(0,-1,3)→0`, `(2,1,3)→2`, `(0,1,3)→1`.
4. `test_arrow_keys_page_only_when_focus_in_pager`: call `qPagerOnKey(ev, ui, node)` with a fake pager (`closest(".crd-qpager")` returns it, `getAttribute("data-qkey")` = K, 3 tabs, `node.contains` → true).
   - `ArrowRight` with a target inside the pager → returns true, `ui.qPage[K]==1`, `preventDefault` was called.
   - A target whose `closest` returns null → false, and `qPage` is untouched.
   - `key:"j"` → false.
   - Any of `shiftKey`/`metaKey`/`ctrlKey`/`altKey` → false.
   - `#msgmodal` with `style.display="flex"` → false.
5. **4b `test_refocus_restores_pager_focus` (F5)**: set `document.activeElement` to a fake tab inside a fake container (`classList.contains("crd-qpager-tab")` true, `closest` → pager with key K, `container.contains` true). `focusedQKey(container)` deep-equals `{key:K,onTab:true}`. `refocusQ(newContainer, f)` → the `focus` spy on the `.is-cur` tab of newContainer's pager K is called with `{preventScroll:true}`. When newContainer has no pager K, there is no call and no throw. `refocusQ(c, null)` is a no-op.
6. *Guard (green before and after):* `test_single_question_ask_renders_unchanged`: an open 1-question decision renders no `crd-qpager` and has `crd-ask-q`, `crd-ask-pill` and the view-only note.
7. `test_closed_single_question_card_shows_answer` (R3/D1/F4): a closed 1-question decision contains `class="crd-answer cr-cfg-row-sub"` and `'</span> Yes</div>'`, contains no `'"Ship?"='` (raw), and does not contain `answer in the session`. The Auggie-shaped closed decision contains `'</span> ok</div>'`.
8. `test_decisions_panel_pages_open_and_closed_multi_q` (D3): `renderDecisions(fakeWrap, multiQDetail, {qPage:{}})` produces a `crd-qpager` per multi-question decision and every question text. The closed 2-question panes show options (`crd-decision-opt`) and one `crd-answer cr-cfg-row-sub` line per answered question. There is no raw `'"Q1"="A"'` and no `Decided:`.
9. `test_phone_awaiting_pages_multi_q`: `renderPhoneAwaiting(fakeNode, multiQDetail, {qPage:{}})` → `crd-qpager` and all 3 questions.
10. `test_spine_marker_title_counts_more`: from `buildMarkers(...)`, the open 3-question title contains `(+2 more)` and the closed 1-question title contains `→ Yes`.
11. `test_modal_payload_lists_every_question`: the 3-question payload contains `1/3`, `2/3`, `3/3` and all three questions. The closed 2-question payload has `→ A` and `→ B` and no `Decided:`. The open 1-question payload equals today's exact string (pin it).
12. *Guard:* `test_auggie_and_empty_degrade`: the Auggie-shaped decision renders the 1-question markup. `questions:[]` → no throw and no `crd-qpager`. `decisions:[]` in the panel → the empty state.
13. `test_answer_html_uses_config_note_class` (D1, F7):
    - `answerHtml(null, "**x**")` starts with `<div class="crd-answer cr-cfg-row-sub">` and contains `→` and `<strong>x</strong>`.
    - `answerHtml(null, "")` → `""`.
    - Python-side checks: `ext_cr_dialogs.css` still has `.cr .cr-cfg-row-sub {` with `11.5px`. `ext_cr_detail.css` has a `.cr .cr-cfg-row-sub.crd-answer` rule whose body has **no** `font` declaration, and contains `.cr .crd-answer code`. `ext_cr_detail.js` contains none of `crd-decision-answer`, `crd-ask-answer` or `crd-qpager-answer`.
14. `test_every_answer_path_uses_answer_html`: count `class="crd-answer cr-cfg-row-sub"`:
    - in `entryHtml(closed2q)` with `qPage` stepped to each page (each page's answer appears);
    - in `renderDecisions` output: exactly 4 (3 per-question answers plus the Auggie fallback).

Run the gate. Every new test should be red except 6 and 12.

### Step 2 — server: the `aitracker/providers/claude.py` tool_result branch (`:2263-2265`)
```python
if rid in asks:                                # the user's answer to an AskUserQuestion
    if b.get("is_error"):                      # declined / interrupted / tool error (F2): never tool boilerplate
        m = re.search(r"the user said:\s*(.*?)(?:\n\s*\n|$)", rtext, re.S)
        a = ("Declined" + (" — " + m.group(1).strip()[:500] if m and m.group(1).strip() else "")
             if rtext.startswith("The user doesn't want to proceed") else "No answer recorded")
        asks[rid]["answer"] = a
        asks[rid]["open"] = False
    else:
        a = re.sub(r"^(?:Your questions have been answered:|The user answered:)\s*", "", rtext)
        a = re.sub(r"\.?\s*(?:You can now continue with these answers in mind\.|Read the answers carefully\b.*)\s*$",
                   "", a, flags=re.S).strip()
        asks[rid]["answer"] = a[:2000]
        asks[rid]["open"] = False
        ans = r_.get("answers") if isinstance(r_, dict) else None     # r_ = this record's toolUseResult (:2169)
        ann = r_.get("annotations") if isinstance(r_, dict) else None
        by_q = {str(k)[:500]: v for k, v in ans.items()} if isinstance(ans, dict) else {}
        for q in asks[rid]["questions"]:
            v = by_q.get(q["q"])
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)                        # multiSelect (R1)
            if isinstance(v, str) and v:
                n = ((ann.get(q["q"]) if isinstance(ann, dict) else None) or {})
                n = n.get("notes") if isinstance(n, dict) else None
                if isinstance(n, str) and n.strip():
                    v = v + " — notes: " + n.strip()[:300]              # the user's own note (F3)
                q["answer"] = v[:500]
```
Notes on Step 2:
- The pair parse is cut (F1). Auggie is untouched; `auggie.py:598` already strips `User responded:`.
- Update the shape comment at `ext_cr_detail.js:38` to `questions:[{q,header,options[],answer?}]`.
- Run I1, I2 and I4 → green.

### Step 3 — helpers in `aitracker/web/ext_cr_detail.js` (ES5 `var`, just above `entryHtml` `:3279`)
- `qKey(d)` → `String(d.t || "") + "#" + (d.questions || []).length`.
- `qPageStep(i, dir, n)` → `Math.max(0, Math.min(n - 1, i + dir))`.
- `qAnswer(d, q, n)` → `q.answer || (n <= 1 && !d.open ? (d.answer || "") : "")`. This is the single fallback rule, used by every path.
- `answerHtml(ctx, text)` → `text ? '<div class="crd-answer cr-cfg-row-sub"><span class="crd-answer-arrow" aria-hidden="true">→</span> ' + mdHtml(ctx, text) + "</div>" : ""`. This is the **only** place answer HTML is built.
- `questionPagerHtml(d, ctx, ui, optCls, showOpts)` builds:
  - the wrapper `<div class="crd-qpager" data-qkey="esc(KEY)" tabindex="-1" role="group" aria-label="N questions">`;
  - the head:
    - a `←` step: `<button type="button" class="crd-qpager-step[ is-dim]" data-act="qpage-step" data-dir="-1" aria-label="Previous question"[ aria-disabled="true"]>←</button>`;
    - `<div class="crd-qpager-tabs" role="tablist">`, with one `<button type="button" role="tab" class="crd-qpager-tab[ is-cur]" data-act="qpage-go" data-i="i" aria-selected="true|false" tabindex="0|-1">` per question. The tab label is (`qAnswer(d,q,n)` ? `☒` : `☐`) + `" "` + (`esc(q.header)` or `"Q"+(i+1)`);
    - a `→` step (dim at n-1);
    - `<span class="crd-qpager-pos mono">i+1/N</span>`;
  - one pane per question: `<div class="crd-qpager-pane" role="tabpanel" data-i="i"[ hidden]>` holding `<div class="crd-qpager-q">` + `mdHtml(ctx,q.q)` + `</div>`, then the options (`'<div class="' + optCls + '">' + mdHtml(ctx,o) + '</div>'`, only when `showOpts`), then `answerHtml(ctx, qAnswer(d, q, n))`.

  The current index is `qPageStep(((ui && ui.qPage) || {})[key] || 0, 0, n)`.
- `applyQPage(pagerEl, i)` changes the DOM only: `hidden` on panes; `is-cur`/`aria-selected`/`tabindex` on tabs; `is-dim`/`aria-disabled` on the steps; the `.crd-qpager-pos` text.
- `goQPage(node, ui, key, i)` → `ui.qPage[key] = i`, then `applyQPage` on every `.crd-qpager` in `node` whose `getAttribute("data-qkey") === key`. Use a loop with a compare; no selector escaping.
- `focusFirstCur(pg)` → `var t = pg.querySelector(".crd-qpager-tab.is-cur"); (t || pg).focus({ preventScroll: true })`. Wrap it in try/catch and fall back to `focus()`.
- `qPagerOnKey(ev, ui, node)` returns false unless all of these hold:
  - `ev.key` is `ArrowLeft` or `ArrowRight`;
  - none of `shiftKey`/`metaKey`/`ctrlKey`/`altKey` is set;
  - neither `#msgmodal` nor `#diffmodal` has `style.display === "flex"`;
  - `pg = ev.target && ev.target.closest && ev.target.closest(".crd-qpager")` is non-null and `node.contains(pg)`.

  Then:
  - `n` = the tab count;
  - `goQPage(node, ui, key, qPageStep(ui.qPage[key] || 0, ev.key === "ArrowRight" ? 1 : -1, n))`;
  - if `ev.target` is a tab, `focusFirstCur(pg)`;
  - `ev.preventDefault()`;
  - return true.
- `focusedQKey(container)` → `var a = document.activeElement; var pg = a && container.contains(a) && a.closest && a.closest(".crd-qpager"); return pg ? { key: pg.getAttribute("data-qkey"), onTab: a.classList.contains("crd-qpager-tab") } : null`.
- `refocusQ(container, f)`: if `f`, find the pager in `container` with that `data-qkey` (loop with a compare), then `f.onTab ? focusFirstCur(pg) : pg.focus({preventScroll:true})`. It is a no-op when the pager is gone.

### Step 4 — wire the paths (same file)
- **Timeline card.** `entryHtml(e, ctx, diagram, ui)`; `renderTimelineEntries` (`:3554`) passes `ui`. In the ask branch (`:3318-3334`):
  - n>1: `questionPagerHtml(d, ctx, ui, "crd-ask-pill", true)` replaces `crd-ask-q` + `crd-ask-opts`. If the decision is closed and **no** question has its own answer, also add `answerHtml(ctx, d.answer)` under the pager.
  - n≤1 closed: add `answerHtml(ctx, qAnswer(d, q0, 1))` after the opts.
  - `crd-ask-note` only when `d.open`. Open 1-question markup stays byte-identical, and the mini-head is unchanged.
- **Timeline repaint** (`:3548-3556`). The condition gains `|| openAsks !== ui.timelineOpenAsks` (R8, where `openAsks` = the open ask count in `filtered`). Set `ui.timelineOpenAsks = openAsks` beside `ui.timelineSeen = …`. Put `var fq = focusedQKey(scrollEl);` before the `innerHTML` write and `refocusQ(scrollEl, fq);` after `upgradeMermaidIn`.
- **Decisions panel.** `renderDecisions(wrap, session, ui)` (`:2784`; the call at `:2323` passes `ui`). In `renderQ`:
  - n>1: `questionPagerHtml(d, null, ui, "crd-decision-opt", true)` replaces `crd-decision-q` + opts. If closed with no per-question answer, add `answerHtml(null, d.answer)`.
  - n≤1: the question and options are unchanged. The `Decided: …` line (`:2796`) becomes `isOpen ? "" : answerHtml(null, qAnswer(d, q0, 1))`.
  - The function ends with `if (wrap._qHtml !== html) { var fq = focusedQKey(wrap); setPanelBody(wrap, html); wrap._qHtml = html; refocusQ(wrap, fq); }`. `setPanelCount` and the tint above stay unconditional.
- **Phone card.** `renderPhoneAwaiting(node, session, ui)` (`:1170`; the call at `:2324` passes `ui`). n>1: `questionPagerHtml(d, null, ui, "crd-phone-awaiting-opt", true)` replaces `crd-phone-awaiting-q` + opts. `card.hidden = false` stays **outside** the skip. The `innerHTML` write goes through the same `_qHtml` skip plus `focusedQKey`/`refocusQ` on `card`. Reset `card._qHtml = ""` in the `!open.length` early return (`:1174`).
- **Modal payload** `timelineEntryModalPayload` (`:3591`):
  - n>1: one block per question, `"**" + (i+1) + "/" + n + (header ? " · " + header : "") + "** — " + q.q`. Add `- option` lines when `d.open`, and `"→ " + qAnswer(d, q, n)` when it is non-empty. The footer `→ ` + `d.answer` appears only when the decision is closed and no question has its own answer. The view-only line appears when open.
  - n≤1 open: byte-identical to today.
  - n≤1 closed: `:3601` becomes `"\n→ " + qAnswer(d, q0, 1)`.
- **Spine** `buildMarkers` (`:710-711`): title = `q0.q + (n > 1 ? " (+" + (n - 1) + " more)" : "") + (n <= 1 && !d.open && qAnswer(d, q0, 1) ? " → " + qAnswer(d, q0, 1) : "") + " · " + fmtClock(t)`. It is escaped by `esc` at `:2689`.
- **Click delegation** (`:1805`), after the `.codecopy` early return and before `closest("[data-act]")`: `var pg = ev.target.closest && ev.target.closest(".crd-qpager"); if (pg && !pg.contains(document.activeElement)) pg.focus({ preventScroll: true });`. In the switch:
  - `case "qpage-go"` → `goQPage(node, ui, pg.getAttribute("data-qkey"), +t.getAttribute("data-i")); focusFirstCur(pg); break;`
  - `case "qpage-step"` → `goQPage(node, ui, key, qPageStep(ui.qPage[key] || 0, +t.getAttribute("data-dir"), n)); focusFirstCur(pg); break;`, where `n` is pg's tab count.

  A click on pane text inside a timeline card still opens the entry modal, as today.
- **Keydown.** Make the first line of the existing `node.addEventListener("keydown", …)` (`:1763`) `if (qPagerOnKey(ev, ui, node)) return;`. Do not touch the document handler at `:2146`.
- **State.** In the `ui` literal (`:1582`), add `qPage: {}, timelineOpenAsks: -1`. In `session:reset` (`:1784-1789`), add `ui.qPage = {}; ui.timelineOpenAsks = -1;`. No `qActive`, no `focusin`.
- **Classic `app.js`: untouched** (F6). It inherits the Step 2 text cleanup through `md(x.answer)` at `app.js:2174`.

### Step 5 — CSS `aitracker/web/ext_cr_detail.css`
- Delete `.cr .crd-decision-answer` (`:1096`) and add `.cr .cr-cfg-row-sub.crd-answer { color: var(--text-secondary); margin-top: 4px; }` and `.cr .crd-answer-arrow { color: var(--text-muted); }`. There is **no** font declaration, because the typography comes from `.cr .cr-cfg-row-sub` (`ext_cr_dialogs.css:362`).
- Add `.cr .crd-answer code,` to the selector list at `:1490-1494` (F7).
- Pager rules:
  - `.crd-qpager:focus{outline:none}`
  - `.crd-qpager:focus-visible{outline:2px solid var(--line-default);outline-offset:2px}`
  - `.crd-qpager-head{display:flex;align-items:center;gap:6px}`
  - `.crd-qpager-tabs{display:flex;flex-wrap:wrap;gap:4px;flex:1;min-width:0}`
  - `.crd-qpager-tab{white-space:nowrap;max-width:14ch;overflow:hidden;text-overflow:ellipsis;font:inherit;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line-subtle);background:none;color:var(--text-secondary)}`
  - `.crd-qpager-tab.is-cur{color:var(--text-primary);border-color:currentColor;font-weight:600}`
  - `.crd-qpager-step{background:none;border:0;color:inherit;font:inherit}`
  - `.crd-qpager-step.is-dim{opacity:.35}`
  - `.crd-qpager-pos{font-size:10.5px;color:var(--text-muted)}`
  - in the `@media (max-width:600px)` block (~`:1893`): `.crd-qpager-step,.crd-qpager-tab{min-height:44px;min-width:44px}`

  All pager rules are prefixed `.cr `. Leave no stray `*/`.

### Step 6 — gate, red proof, manual check
- **Gate:** run `unset TRACKER_AUTH; python3 -m unittest tests.test_cr_timeline tests.test_integration`, and confirm the node tests ran and were not skipped. Then run `unset TRACKER_AUTH; make check` → `selfcheck ok`, with a Bash timeout ≥ 400000 ms. `Killed: 9` means OOM: rerun per module. One term_vt backstop test is known to be flaky.
- **Red proof:** do these one at a time with scoped Edits (never `git stash`), re-run the named tests, then restore:

  | Revert | Tests that must go red |
  |---|---|
  | the `questionPagerHtml` call in `entryHtml` | 1, 2 |
  | the `list` join | I1 |
  | the notes append | I1 |
  | the tail regex | I2 |
  | the `is_error` branch | I4 |
  | `answerHtml`'s `cr-cfg-row-sub` class | 13, 14 |
  | `qPagerOnKey`'s `closest(".crd-qpager")` gate | 4 (outside-pager case) |
  | `refocusQ`'s `onTab` branch | 4b |
  | `qAnswer` order (`d.answer` first) | 7, 8 |
- **Manual:** restart with `make serve` (UI change). Then check:
  - a 4-question decision in the card and in the panel;
  - click a tab in Safari **and** Chrome, then ←/→ pages;
  - click outside, then ←/→ do nothing;
  - wait ≥ 4 s with focus on a panel tab, then ←/→ still work;
  - the modal's ←/→ still step entries;
  - the terminal keeps its arrows;
  - at 390 px width the tabs wrap;
  - a declined ask reads `→ Declined`;
  - no `"Q"="A"`, `You can now continue…` or `STOP what you are doing` text anywhere.

### Step 7 — implementation review (opus) → `/branch-sync` → push the branch to `personal`; **HOLD `/tracker-push`** (contract).

### Risky spots + fallback
1. **Focus surviving repaints.** The three writers are the only places that emit pager markup. Grep the `questionPagerHtml` callers in review. Test 4b covers the helpers. Fallback: also accept `pg.matches(":hover")` in `qPagerOnKey`.
2. **`refocusQ` stealing focus.** It fires only when focus was inside a pager in the same container before the write, and it uses `preventScroll`.
3. **New Claude Code result wording** (a new prefix or tail, or new is_error text). It degrades to today's behaviour: the raw text is shown, cleaned where known.
4. **Class reuse coupling.** Restyling `.cr-cfg-row-sub` restyles answers too. That is intended, and test 13 pins it.

### Decisions the user may overrule
- F6: the classic view is left as-is (it only gets the cleaned server text). The alternative is per-question `→ answer` lines in classic, which is about 2 lines of JS plus CSS.
- F2 wording: `Declined` / `Declined — <their message>` / `No answer recorded`.
- Carried over from v3: clicking pane text in a timeline card still opens the entry modal; answer colour is `--text-secondary` rather than the Config note's `--text-muted`.

## Reconciliation 2 — v3 re-review (main thread, 2026-11-18)

| # | Finding | Verdict | Note |
|---|---|---|---|
| F1 | `"Q"="A"` text parse is dead + fails on 23% | confirmed — cut | all 318 real answers carry `toolUseResult.answers` |
| F2 | declined/error asks show tool boilerplate as answer | confirmed | `Declined` / `Declined — <msg>` / `No answer recorded`; test I4 |
| F3 | user notes on an answer dropped | confirmed (low) | small; part of "render cleanly" |
| F4 | test 6 can never fail (`esc` doesn't escape `"`) | confirmed | assert exact fragment |
| F5 | no test for focus surviving repaint | confirmed | test 4b |
| F6 | classic app.js change outside contract | confirmed — cut | classic still gets cleaned server text |
| F7 | inline `code` in answer unstyled | confirmed (low) | one selector added |

Verdict: **Clean plan v4 supersedes v3.** Sent to user for sign-off.

## Implementation (sonnet)
Sign-off (user, 2026-11-19): "Approve, implement (Recommended)" on Clean plan v4

**Files / functions changed**
- `aitracker/providers/claude.py` tool_result branch for `asks`: `is_error` -> `Declined` / `Declined — <msg>` / `No answer recorded`; strips `Your questions…`/`The user answered:` prefix and the `in mind.` / `Read the answers carefully…` tail; per-question `answer` from `toolUseResult.answers` (list joined, `— notes:` from annotations).
- `aitracker/web/ext_cr_detail.js`: v1 talk predicate kept; new `qKey, qPageStep, qAnswer, answerHtml, questionPagerHtml, applyQPage, goQPage, focusFirstCur, qPagerOnKey, focusedQKey, refocusQ`; wired in `entryHtml(…, ui)` (ask branch), `renderTimelineEntries` (passes `ui`, `timelineOpenAsks` repaint trigger, focus restore), `renderDecisions(wrap, session, ui)` (`_qHtml` skip), `renderPhoneAwaiting(node, session, ui)`, `timelineEntryModalPayload`, `buildMarkers`, click delegation (`qpage-go`/`qpage-step`), keydown first line, `ui.qPage`/`timelineOpenAsks` + `session:reset`; `_internal` exports; shape comment line 38.
- `aitracker/web/ext_cr_detail.css`: `.crd-decision-answer` replaced by `.cr .cr-cfg-row-sub.crd-answer` + pager rules + `.cr .crd-answer code` + 44px touch targets at <=600px.
- Classic `app.js` untouched (per v4 F6).

**Tests (red -> green)**
- `tests/test_integration.py` (TestDecisions): `test_claude_decisions_strip_trailer_and_alt_prefix` (I2, new method; existing `test_claude_decisions` left as is), `test_claude_multi_question_answers` (I1), `test_claude_declined_ask_is_clean` (I4). Red on baseline (3 failures/errors), green after Step 2.
- `tests/test_cr_timeline.py`: 15 new tests (pager render, ui page/clamp, step clamp, arrow-key gating, refocus, single-question guard, closed single answer, panel, phone, spine marker, modal payload, auggie/empty degrade, answerHtml + CSS pins, every-answer-path, wiring pin). All 15 red before implementation (helpers not exported), green after.
- Revert-proofs (scoped, restored; each went red as named): v1 talk predicate -> talk_only_shows_* x2; pager call in entryHtml -> 1,2 and answer_path; list join -> I1; notes append -> I1; tail regex -> I2+I1; is_error branch -> I4; answerHtml class -> 13,14,7; qPagerOnKey closest gate -> 4; refocusQ onTab -> 4b; qAnswer order -> 7 and spine-marker test.

**Gate**: `tests.test_cr_timeline` 33 tests OK (node tests ran, 0 skipped); `tests.test_integration` 129 OK; `make check` -> `selfcheck ok`.

**Deviations**
- I2 added as a separate test method rather than extending `test_claude_decisions` (shared helper `_ask_session`).
- Guard tests 6 and 12 were red on baseline only because `entryHtml` was not yet exported; they are pure guards after export.
- Test 8 does not separately pin per-question answer-line count (test 14 pins 4 total). Test 10 asserts the closed 1-question spine title via `Ship?` + `→ Yes`.
- Step buttons use `aria-disabled="true|false"` (not attribute removal) so the node stub works; initial render omits it when not dim.
- Not done: manual browser checks (Step 6), implementation review, branch-sync, commit/push (per instructions).

## Contract addendum 3 (verbatim, user, 2026-11-19)

> in the end /branch-sync -> /tracker-push

Supersedes "HOLD /tracker-push" in addendum 2: ship = /branch-sync, then /tracker-push (push branch + fast-forward personal/main; main push run by the main thread).

## Implementation review — client (opus)

Verdict: no functional client defect. Two findings:

- **F1 (Medium, test gap).** The focus-restore at the three repaint sites (`refocusQ` in renderPhoneAwaiting, renderDecisions, renderTimelineEntries), the open-ask repaint trigger (`openAsks !== ui.timelineOpenAsks`) and the Safari click-focus line had no failing test; each could be deleted and the suite stayed green. Fix: tests only, production unchanged.
- **F2 (Low, UX).** Clicking a non-button spot of a timeline card's pager head (the `2/3` counter, the gap between tabs) fell through `closest("[data-act]")` to `.crd-entry` and opened the entry modal. Fix: in the node click handler, right after the Safari focus line, `if (pg && ev.target.closest(".crd-qpager-head") && !ev.target.closest('[data-act^="qpage-"]')) return;`. Pane-text clicks still open the modal; panel/phone unchanged.

Checked clean: no `questions[0]` in multi-question paths; arrow keys act only inside a focused pager and defer to #msgmodal/#diffmodal; page clamp and dimmed ends; esc covers & < > " '; `node --check` OK on all web/*.js and the assembled script; CSS balanced; Auggie and empty sessions degrade to the single-question render.

## Client fixes applied (sonnet)

Tests added in tests/test_cr_timeline.py: driver cases `panelRefocus` / `phoneRefocus` (shared `repaintCase`; focused tab + changed html => `focus({preventScroll:true})` called once), `test_panel_repaint_restores_pager_focus`, `test_phone_repaint_restores_pager_focus`, `test_repaint_sites_wired_source_pins` (timeline/panel/phone/click-handler order), and a `closest(".crd-qpager-head")`-before-`closest("[data-act]")` pin in `test_pager_wired_on_click_key_and_state`. F2 fix applied in ext_cr_detail.js.

Red -> green (mutant applied, suite RED, restored, green): remove `refocusQ(card, fq)` (phone + pins red); `refocusQ(wrap, fq)` (panel + pins red); `refocusQ(scrollEl, fq)` (pins red); `openAsks !== ui.timelineOpenAsks` (pins red); the Safari `pg.focus` line (pins red); `var fq = null` in renderDecisions (panel + pins red) and renderPhoneAwaiting (phone + pins red). F2 pin was red before the fix (assertion failed), green after. Gate: `python3 -m unittest tests.test_cr_timeline` 36 tests OK, node tests ran.

## Implementation review — server (opus)
Scope: `aitracker/providers/claude.py` AskUserQuestion answer branch (:2263-2289), I1/I2/I4 in `tests/test_integration.py`, Auggie shape. Method: parser run on every real transcript containing AskUserQuestion (944 files, 387 decisions, 1011 questions); in-memory mutants (source string patched and exec'd, no file edits) for red proofs.

**Verified (no defect):**
- Boilerplate: 0 decisions/questions contain `Your questions have been answered` / `You can now continue` / `Read the answers carefully` / `STOP what you are doing` (the one `The user answered` hit is a question that quotes that phrase).
- multiSelect joined (`2bda7c0d`: `pmondal@…, Merge Sim <…>, Bot commits (…), r <r@r>`); notes appended (`82ce95d1` D1: `Book + note (Recommended) — notes: check for the JIRA comment…`); a skipped question in a 4-question ask correctly has no `answer`; Declined forms: corpus has only the two `is_error` forms tested by I4 (19 + 5).
- Red proofs (each mutant → named test red): list join → I1; notes → I1; tail regex → I2+I1; `The user answered:` prefix → I2; `is_error` branch → I4; `the user said` capture → I4; per-q assignment → I1. `TestDecisions`: 5 tests OK.
- Auggie: `auggie.py` unmodified; `:598`/`:675` still emit `{t, open, answer, questions:[{q, header, options}]}` with no per-q `answer`; the SPA's `qAnswer` falls back to `d.answer`.

**S1 (medium-high, PRE-EXISTING; it defeats this feature on real data) — blob replays reopen answered asks and drop their per-question answers.**
- Defect: `_transcript_pass` (claude.py:2148-2160 record loop) does not skip `_BLOB_TYPES` (`:1832`; the other pass skips them at `:1854`). Claude Code writes `api-request-blob` records that replay earlier messages with no `timestamp` and no `toolUseResult`. An assistant-role blob re-runs `:2390` `asks[bid] = {"t": None, "open": True, …}`, which wipes the real answer and the per-question answers. A following user-role blob re-closes the ask without per-question answers.
- Repro: in session `0f4ee7b4-9a96-484b-8a7d-3ea03a6c9845` all 9 asks have a real answered `type:user` record. `parse_session` returns 6 open (`waiting: True`) and 3 closed with no `questions[i].answer`. The UI then falls back to the raw `"<439-char question>"="Go, implement it"`.
- Corpus: 54/387 decisions have `t=None`, 28 are falsely open across 8 sessions, and 25 closed decisions have no per-question answers. HEAD gives the same 6 open for `0f4ee7b4`, which is why this is pre-existing. With the fix below (in memory, fresh run): `t=None` 0, open 0, closed-without-per-q 1 (the `The user did not answer the questions.` form).
- Fix direction: ignore blob records for the `asks` map only. Do NOT change narration, commands or files in this diff. A global blob skip in `_transcript_pass` is probably right, but it is a separate gap.
- Way: at `:2385` use `elif name == "AskUserQuestion" and o.get("type") not in _BLOB_TYPES:`, and at `:2263` use `if rid in asks and o.get("type") not in _BLOB_TYPES:`.
- Test: add I5 `test_claude_ask_blob_replay_ignored` in `TestDecisions`. Records: a real tool_use `a0` (with timestamp); a real user answer with `toolUseResult.answers`; then `{"type":"api-request-blob","message":{"role":"assistant","content":[<same tool_use>]}}`; variant B appends a user-role blob carrying the same tool_result. Expect 1 decision, `open` False, `t` == the original ts, `questions[0]["answer"]` == the value, and `parse_session(path)["waiting"]` False. Today it is red (`open` True, `t` None).

**S2 (low; answers the coordinator's `4af131c5` question) — the top-level `answer` is the raw `"<question>"="<answer>"` pair.**
- Not caused by the annotations/preview handling or the tail strip. In `4af131c5` the tail strip worked (`…?"="Push and rerun all gates"`); the leading text is the question half of the pair. This is v4's design (F1 cut the pair parse), and it is not a regression: HEAD gives the same text plus the tail.
- Where the user sees it: classic `app.js:2174` always shows it. `ext_cr_detail.js` (`:2825`, `:3465`, `:3745`, `qAnswer` `:3322`) shows it only when no question has its own answer, which in practice is the S1 cases. Preview answers also carry `selected preview:\n<ASCII box>` in it (3 in the corpus).
- Fix direction: when at least one per-question answer was resolved from `toolUseResult.answers`, set the top-level `answer` to those answers joined. Keep the cleaned text otherwise (Declined / No answer recorded / no toolUseResult). Do NOT change Auggie or the per-question values.
- Way: after the per-question loop (~`:2289`): `got = [q["answer"] for q in asks[rid]["questions"] if q.get("answer")]` and `if got: asks[rid]["answer"] = "; ".join(got)[:2000]`.
- Test: in I1 add `assertEqual(dec[0]["answer"], "A — notes: only on staging; x, y")`, which is red today. I2's no-toolUseResult cases keep `'"Ship it now?"="Yes"'` as their guard.

**Info (no change):** a non-error form `The user did not answer the questions.` (1 in the corpus, `9383c8c3`) shows as-is. A multi-paragraph `the user said:` message is cut at its first blank line, which is needed to drop the `\n\nNote:` trailer.

## Server fixes applied (sonnet)
- S1: `aitracker/providers/claude.py` — answer branch (`if rid in asks and o.get("type") not in _BLOB_TYPES`) and ask creation (`elif name == "AskUserQuestion" and o.get("type") not in _BLOB_TYPES`); blob handling elsewhere untouched.
- S2: after the per-question loop, `got = [q["answer"] ...]`; if any, top-level `answer = "; ".join(got)[:2000]` (Declined / No answer recorded unchanged).
- Tests (`tests/test_integration.py`, TestDecisions): I5 `test_claude_ask_blob_replay_ignored` (variants A assistant blob, B + user blob); I1 `test_claude_multi_question_answers` now asserts top-level answer `A — notes: only on staging; x, y`.
- Red before fix: 2 failures (I5 `True is not false`; I1 raw `"Q1 text"="A", ...` pair). Green after: `Ran 130 tests ... OK` (tests.test_integration).
- Real data 0f4ee7b4: 9 decisions, 0 open, waiting False, 0 with t=None (was 6 open).
