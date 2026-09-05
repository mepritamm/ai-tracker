# Adversarial re-audit — 03-detail-view.md vs implementation

Scope: `aitracker/web/ext_cr_detail.js` (2573 lines), `ext_cr_detail.css` (1600 lines), `ext_cr_boot.js`; provider fields cross-checked in `providers/claude.py`, `providers/auggie.py`, `registry.py`. Read-only, no files edited.

Method: six parallel sub-agent passes (header/actions/fork-banner, progress spine, State column, Conversation timeline, Evidence column, phone layout), each independently re-verified against real code (not code comments). The Evidence-column sub-agent got confused mid-run about which side of the parent/fork relationship it was on and, after being redirected, ended up re-auditing the *entire* doc solo and overwriting this file with its own version; that version's genuinely new findings (terminal context-readout format, stale flag-card copy, phone stop-button) are merged in below, while its phone-layout section is superseded by the original dedicated phone-layout pass, which found a more severe breakpoint bug it missed. All disk-file claims below were re-confirmed directly (`grep`/`sed -n`) before being kept.

## Main table

| # | Doc section | Doc says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 1a | Header row1 (identity) | source label · divider · metaline · state pill · agent pill | ext_cr_detail.js:908-916, 1535-1587 | MATCH | — |
| 1b | Header row2 (goal) | serif goal, rename pencil, pinned pill | ext_cr_detail.js:932-937, 1588-1597 | MATCH | — |
| 1c | Header row3 (stat chips) | 7 chips, always visible desktop, hidden phone | ext_cr_detail.js:941-943, 706-752 | MATCH (settled decision) | — |
| 1d | Actions across **two rows** (R1 Search+Flag; R2 Terminal/Resume/External) | ext_cr_detail.js:924-931 | **DRIFT — all 6 actions collapsed into ONE row** (`.crd-row1-actions`) | HIGH |
| 1e | Search/Flag are labeled pills | ext_cr_detail.js:925-926 | DRIFT — icon-only buttons, label only in title/aria | MED |
| 1f | "Resume here" copy | ext_cr_detail.js:928 | DRIFT — reads "Resume" | LOW |
| 1g | (not in doc's Actions list) | "Queue a note" header button, ext_cr_detail.js:929 | EXTRA — doc's note UI is the Plan panel's own input | LOW |
| 1h | Dark theme: solid+outline → white tone | css:311-315 | MATCH | — |
| 1i | flag_text via native `title` on state pill | ext_cr_detail.js:1567-1577; registry.py:140 | MATCH | — |
| 1j | Back line copy + hint | ext_cr_detail.js:895, 1518-1533 | MATCH | — |
| 1k | Fork banner: full-width, between header and spine | ext_cr_detail.js:1092-1104, 1649-1674 | **DRIFT — rendered as a small card at bottom of Evidence column**, wrong location/treatment | HIGH |
| 1l | Fork banner exact copy ("Resume was refused…") | ext_cr_detail.js:1665-1667 | DRIFT — drops the causal "Resume was refused…background agent" clause entirely | MED |
| 1m | Shows nothing when lineage unknown | ext_cr_detail.js:1670-1673 | MATCH | — |
| 2 | Todos strip | superseded by progress spine (README decision 9); doc has no separate strip | grep confirms no leftover `todo-strip`/`pill-chain` element anywhere | MATCH (correctly absent) | — |
| 3a | Grid `.78fr 1.34fr .78fr`, gap 18, order State/Conversation/Evidence | css: grid-template; js:992-1025 | MATCH | — |
| 3b | Expand-all/Collapse-all scoped per column, not global | js:1173-1180 (`data-col` routes to `STATE_PANELS`/`EVIDENCE_PANELS` only) | MATCH | — |
| 3c | 1024–1279 → two columns; <1024 → one, order Convo→State→Evidence | css:1290-1307 | MATCH | — |
| 5 | Every panel collapsed by default except Timeline; persisted per-panel-per-session; tint survives collapse | js:216-241, 856-873, 1483-1491, 1756 | MATCH | — |
| 6a | Narration+prompts = one merged timeline, not two panels | js:440-478, 1035-1048, 1107-1138 | MATCH | — |
| 6b | Column/panel head copy, filters | js:1000-1007, 1107-1130 | DRIFT — extra per-kind filter buttons layered beyond doc's plain all/talk-only pair | LOW |
| 6c | Entry anatomy (gutter colors, bubbles, radii) | js:2105-2184; css:1071-1200 | MATCH | — |
| 6d | Tool-call duration + result counts | js:2166-2181 | DRIFT — no such field exists anywhere in the parser; honestly omitted, not fabricated | LOW |
| 6e | Live entry pinned bottom, layout-stable | js:2497-2529; css:1114-1127 | MATCH | — |
| 6f | Paging footer + scroll-preserve-unless-stuck | js:1143-1154, 2375-2399 | MATCH | — |
| 6g | Chat ordering (doc implies oldest-top/newest-bottom via "pinned at the bottom"/"older page in as you scroll") | js:1061-1065, 1144-1148 render **newest-first (newest at top)** | DRIFT — coherent but inverts doc's literal chat metaphor; deliberate, not confirmed by doc | MED |
| 6h | Degraded providers: honest panel, filter hidden (Auggie excluded, Augment-ext degraded) | js:2070-2093 | MATCH | — |
| 7a | Spine math: time-proportional, 88% cap, 3% floor, >16→"N earlier" | js:274-411, 1676-1747 | MATCH | — |
| 7b | Header/footer copy, segment radii, done/running/pending treatment, event gutter 5 marker kinds | js:1679-1747; css:436-611, 490-491 | MATCH | — |
| 7c | Collision offset "10px" for markers <2% apart | js:402-405 offsets by 2 **percentage points**, not a fixed pixel amount — separation shrinks on a narrow spine | DRIFT | LOW |
| 7d | "click a segment to jump the chat there" | js:1245-1249, 1440-1448 vs. every timeline entry's `data-todo-text` hardcoded `""` (js:2129, 2140) | **MISSING/BROKEN — match key never populated, click does nothing** | HIGH |
| 7e | No leftover progress-ring code | grep across all 3 files: none | MATCH | — |
| 7f | `role="img"` + aria-label summary; segments focusable | js:1746 / 1703 | MATCH | — |
| 8 | Decision panel view-only, no write path | js:1751-1781 only reads `d.answer`; grep of both files for fetch/POST near "decision"/"answer": none | MATCH | — |
| 10 | Provider degradation — see matrix below | — | mostly MATCH, one real gap | — |

## Area 4 — per-panel sub-table

**State column** (order matches doc: Decisions → PRs → Links → Summary → Plan):

| Panel | Verdict | Note |
|---|---|---|
| 1 Decisions & open questions | MATCH | footer copy exact; "Decided earlier" divider present (js:1751-1781) |
| 2 Pull requests | DRIFT (MED) | doc wants a real title; parser (`util.py collect_prs`) never captures one — code renders `—` honestly instead of fabricating (js:1783-1810). Data-shape gap, not a code bug. |
| 3 Links (NEW) | MATCH | two groups, forest/dusk labels, verb text, agent tag, dedup+×N, footnote verbatim, localhost included (js:1812-1833) |
| 4 Session summary | MATCH | Goal/Now/So-far present, Now gets `.crd-summary-now` (600 weight not independently re-verified — LOW) |
| 5 Plan on the go | MATCH | header/delivery-chip copy exact for all 3 states (branches on real `session.push_when`); footer input+push exact (js:1848-1871) |

**Evidence column:**

| Panel | Verdict | Note |
|---|---|---|
| 1 Files | DRIFT (MED) | row structure/created/edited/agent/md tags MATCH (js:1875-1891); but **basename is not set in 500 weight** — whole path is plain undifferentiated text (css:905-912); and **+N/−N are edit-*op-tallies*, not real added/removed line counts** — no such field exists in either provider (claude.py:1236-1242, auggie.py:409-410), so a coloured "+1" can mean one Write call, not one line. Footer hint text matches. |
| 2 Commands | MATCH | 22px gutter, ok/fail words, header count, honest "--"/"status not recorded" path (js:1893-1932, css:918-940). Dormant today since both providers always emit a real boolean (claude.py:1173-1185, auggie.py:495-502) — correct forward-compatible design. |
| 3 Agents & shells | MATCH | running/finished split, "Show N finished", ×N re-run collapse, state dot+title+wf/×N+open› (js:1956-2017). EXTRA (LOW): an undocumented model-name chip on agent rows (js:1976-1977). Auggie correctly shows the honest degraded-capability card (agents_bg/shells always `[]` for Auggie, auggie.py:659). |
| 4 Run a command | MATCH | mono field + run + exact constraint text (js:2019-2025) |
| 5 Terminal controls | DRIFT (MED) | whole panel correctly hidden when `term_attached` falsy, provider-agnostic (js:2028-2051; registry.py:143-166, shared seam, fail-closed). Model/effort chips correct. But the context readout uses `fmtNum()` — comma-grouped "128,412 / 481,412" — not the doc's abbreviated "128k / 481k" style (js:2047-2048). |

### Header flag-count message — stale claim

`registry.py:131-153` already merges `open_flags`/`flag_text` onto the per-session detail dict — but a stale code comment (js:1606-1607) and the actual zero-flags UI copy (js:1618: *"Open-flag count needs the board's flag store wired into this view (not yet on /api/session)"*) both still claim the field isn't available. It is. DRIFT, MED.

## Area 9 — phone layout, per item

| Doc item | Implementation | Verdict | Severity |
|---|---|---|---|
| Status bar | N/A — OS chrome, no app element in either doc | MATCH | — |
| Back chevron + breadcrumb + "7/11" | `renderPhoneHead` js:785-796, called js:1496; css:1339-1373, shown ≤600px | MATCH | — |
| …but back chevron hit target | css:1345-1359, 28×28px, no expanded hit-area | DRIFT | MED |
| 34px presence orb + state word + current file | `renderPhonePresence` js:801-815; css:1381-1413 orb=34px | MATCH | — |
| Live narration, 21px serif | css:1433-1441 | MATCH | — |
| Spine compressed (bar+gutter only, no per-segment labels) | css:1512-1523 hides labels **only at ≤480px**, not the ≤600px band the rest of phone uses | DRIFT | LOW |
| Chat timeline reused | css order:1 at ≤1024px, same panel DOM | MATCH | — |
| Awaiting question card | `renderPhoneAwaiting` js:820-838, called js:1502; css:1447-1492 | MATCH | — |
| Folded State/Evidence cards | order:3/4, panels genuinely default-collapsed (not `display:none`) | MATCH | — |
| Fixed bottom bar (note field + 48px send + 48px stop) | css:1246 `position: sticky; bottom:0`, shown only inside `@media (max-width:480px)` (css:1512-1523); doc explicitly specifies `fixed` "so note and stop are reachable at any scroll position" | DRIFT — sticky, not fixed; functionally similar in most viewports but not the literal spec, and moot in the band below anyway (see next row) | MED |
| **`.crd-backline` hidden only ≤480px** (css:1513) **while `.crd-phonehead` shows ≤600px** (css:1339,1348) **and `.crd-phonebar` shows only ≤480px** (css:1523) | Confirmed directly via `grep` on the three breakpoints | **DRIFT — in the real 481–600px viewport band, the OLD desktop back-line and the NEW phone back-chevron render simultaneously (duplicated back-nav), and the compose bar (note+send+stop) doesn't exist at all** | HIGH |
| Stop button functional | js:1030-1031 renders `disabled title="Not available yet — there's no server route to stop a running session."` — honestly labeled non-functional, not silently broken | DRIFT | MED |
| All hit targets ≥44px | mostly satisfied; exceptions are the back-chevron above (28×28) and the whole compose bar in the 481–600px band (doesn't exist) | DRIFT | MED |

## Provider-field matrix (non-negotiable: provider-agnostic, honest degradation)

| Field | claude.py | auggie.py | JS degrades honestly? |
|---|---|---|---|
| files[] / commands[] | yes | yes | yes |
| files[].ops (used as +N/−N) | op-tally only, no real diff-line count | same | **No** — presented with diff-stat semantics (+/−) it doesn't have |
| commands[].ok | always real bool | always real bool | yes (dormant "--" path ready, never wrongly shows fake "ok") |
| agents_bg[] / shells[] | populated | always `[]` | yes — Auggie gets the honest degraded-capability card, not a fake empty state |
| prs[].title | field doesn't exist (url/repo/num only) | same | yes — renders `—`, never fabricates a title |
| term_attached | yes (registry seam) | yes (same seam) | yes — whole panel hidden when absent; naturally false for a non-Claude pty too |
| fail_cmd | yes | yes | yes — same predicate as board (`live && fail_cmd`) |
| open_flags / flag_text | yes (registry.py:131-153) | yes (same seam) | **honest for the count itself, but the zero-state UI copy is stale** (see above) |

## Totals by verdict

- MATCH: 34
- DRIFT: 18 (3 HIGH structural — actions-in-one-row, fork-banner placement, phone breakpoint mismatch causing duplicated back-nav + missing compose bar in a real 481–600px band; 1 HIGH functionally-dead spine click-to-scroll; rest MED/LOW)
- EXTRA: 2 (header "Queue a note" button; agent-row model chip)
- MISSING: 1 (spine segment click → timeline scroll is wired but functionally dead — `data-todo-text` never populated)

## Fix list

1. **HIGH** — Split header actions into doc's two rows (R1 Search+Flag, R2 Terminal/Resume/External) instead of one `.crd-row1-actions` row. `ext_cr_detail.js:924-931`.
2. **HIGH** — Move the fork-lineage banner to a full-width row between the header and the spine per the Structure diagram; it currently renders as a small Evidence-column card. `ext_cr_detail.js:1092-1104, 1649-1674`.
3. **HIGH** — Fix the 481–600px phone band: align `.crd-backline`'s hide-breakpoint (currently ≤480px, `css:1513`) and `.crd-phonebar`'s show-breakpoint (currently ≤480px, `css:1523`) to the same ≤600px threshold `.crd-phonehead` already uses (`css:1339`), removing the duplicated back-row and restoring the compose bar in that band.
4. **HIGH** — Populate a real per-todo key on timeline entries (currently `data-todo-text=""` always, `js:2129,2140`) so `scrollTimelineToTodo` (`js:1440-1448`) can actually match and the doc's "click a segment to jump the chat there" works.
5. **MED** — Restore visible Search/Flag pill labels instead of icon-only buttons (`js:925-926`).
6. **MED** — Give files a real basename emphasis (500 weight) and stop presenting the edit-op tally as if it were an added/removed line-diff count, or add an honest "(edits)" qualifier — no real line-diff data exists in either provider (`js:1884-1885`, `css:905-912`).
7. **MED** — Restore the "Resume was refused…background agent" causal clause in the fork-banner copy (`js:1665-1667`).
8. **MED** — Reconsider newest-first ordering of the merged timeline against the doc's oldest-top chat metaphor, or get explicit owner sign-off that this reinterpretation stands (`js:1061-1065`).
9. **MED** — Expand the phone back-chevron's hit area to ≥44px via a `::before` overlay, matching the technique already used for `.crd-iconbtn` (`css:1345-1359`).
10. **MED** — Format the terminal panel's context readout as abbreviated "128k / 481k" instead of comma-grouped (`js:2047-2048`).
11. **MED** — Fix the flag card's stale zero-state copy — `open_flags` is real, wired data now (`js:1606-1607, 1618`; `registry.py:131-153`).
12. **MED** — Change `.crd-phonebar` to `position: fixed` per doc's explicit rationale, or justify sticky as equivalent (`css:1246`).
13. **MED** — Either wire a real stop route for the phone stop button or adjust the doc's expectation that it be an active control (`js:1030-1031`).
14. **MED** — Pull-requests panel title gap is a data-shape limitation, not a code bug — flagged as a REQUIRED ADDITION for the parser (`util.py collect_prs`), not a JS fix.
15. **LOW** — Either remove the extra "Queue a note" header button (doc's note UI lives in the Plan panel) or get it added to doc's Actions spec (`js:929`).
16. **LOW** — Change "Resume" button copy to "Resume here" (`js:928`).
17. **LOW** — Use a literal ~10px pixel nudge for near-colliding spine markers instead of a 2-percentage-point offset, or accept as a documented approximation (`js:402-405`).
18. **LOW** — Align the phone spine's compressed-label breakpoint (currently ≤480px) with the ≤600px threshold the rest of the phone layout uses (`css:1512-1523`).
