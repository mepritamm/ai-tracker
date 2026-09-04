# Drift report — 03-detail-view.md vs. shipped Control Room detail view

Spec: `design_handoff_control_room/03-detail-view.md` (+ README.md decisions 7/8/9, 01-foundations.md for token names only).
Implementation: `aitracker/web/ext_cr_detail.js` (2292 lines), `ext_cr_detail.css` (1367 lines), `ext_cr_boot.js` (rail lives in `ext_cr_board.js`, out of scope), `providers/claude.py`, `providers/auggie.py`.

Legend — Verdict: MATCH / DRIFT / MISSING / EXTRA. Severity: HIGH / MED / LOW.

## 1. Detail header

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 1.1 | "Back line" | `‹ Back to the board` + "1 of 4 needing attention · j / k to move between them" | `ext_cr_detail.js:707-708` skeleton; `renderBackline` (`:1292-1304`) reads `state.triage`, but `ext_cr_boot.js:903` only ever calls `CR.detail.update({session: d, now: d.now})` — `state.triage` is never populated anywhere in the codebase (grep confirms). The hint is therefore **permanently hidden**. | DRIFT | MED |
| 1.2 | Identity row 1 | Source label, divider, metaline, state pill, agent pill | `renderHeader` (`:1306-1346`) implements all five, but metaline is "project · branch · elapsed · tokens · model" not the doc's "ai-tracker · ~/dev/ai-tracker · term-tiers · 41m" (cwd path dropped, model appended) — deliberate per `:1312-1327` comment "FIX drift 1" | DRIFT | LOW |
| 1.3 | Identity row 2 — goal | Serif 29px/1.15 goal, rename pencil, Pinned pill | `:1348-1355`; `session.pinned` is **not on the detail dict** (only on the list dict, `registry.py:70-72`), so the Pinned pill can never show even when true (`:1352-1355` comment "REQUIRED ADDITION") | MISSING (data) | MED |
| 1.4 | Row 3 — 7 stat chips (`files 18 · commands 42 · reads 96 · commits 3 · tests 1 failing · tokens 128,412 · branch term-tiers`), `--`/`N/A` convention | Entire chip row removed. No `crd-chip` stat row, no "N/A"/"Not Applicable" string anywhere in `ext_cr_detail.js` (grep confirms zero hits) | DRIFT | HIGH |
| 1.5 | Actions — two stacked rows: Row1 Search/Flag pills (labelled); Row2 Open terminal (solid) / Resume here (outline) / External (bare) | Collapsed into **one row** (`:726-733`, comment "FIX drift 2"): Search/Flag became icon-only buttons (label only in `title`/`aria-label`, not visible text), plus an unspec'd "Queue a note" button, then Open terminal/Resume/External | DRIFT | MED |
| 1.6 | Button copy "Resume here" | Implementation renders `>Resume<` (`:730`) | DRIFT | LOW |
| 1.7 | Dark theme: solid+outline become white button tone | `ext_cr_detail.css:275-276` `.cr.is-dark .crd-btn-solid, .cr.is-dark .crd-btn-outline` | MATCH | — |
| 1.8 | Fork lineage banner: full-width banner between header and spine | Rendered instead as a small card at the **bottom of the Evidence column** (`renderForkBanner`, `:1407-1432`, comment "FIX drift 3") | DRIFT | MED |
| 1.9 | Fork banner copy/link direction (both directions) | `:1410-1428` implements both `continued_as`/`continued_from` cases with equivalent copy | MATCH (structure moved, copy intent kept) | — |

## 2. Todos strip

The spec's todos strip (implied by decision 9 as feeding the spine) has no standalone panel in `03-detail-view.md` beyond the progress spine — verified doc has no separate "todos strip" section other than the spine. No separate implementation exists either. N/A — not a distinct claim to check.

## 3. The three columns

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 3.1 | Grid | `.78fr 1.34fr .78fr`, gap 18px, padding `16px 24px 22px` | `ext_cr_detail.css:579-584` exact match | MATCH | — |
| 3.2 | Column order/labels | State · Conversation · Evidence | `SKELETON` `:778-804` — State, Conversation, Evidence in that order | MATCH | — |
| 3.3 | 1024–1279px | Two columns: State+Evidence stacked left, Activity(Conversation) right | `ext_cr_detail.css:1250-1257` exact | MATCH | — |
| 3.4 | <1024px | One column, order Activity → State → Evidence | `ext_cr_detail.css:1260-1264` `order: convo=1, state=2, evidence=3` | MATCH | — |
| 3.5 | Eyebrow Expand all/Collapse all per column | State and Evidence eyebrows carry the toggle | `SKELETON :779-783, 796-801` (only State/Evidence, not Conversation — matches doc which doesn't give Conversation this control); click handler `:951-958` scopes strictly to `STATE_PANELS`/`EVIDENCE_PANELS` by `data-col` | MATCH | — |

## 4. Every panel

| # | Panel | Present? | Fields/copy correct? | Verdict | Severity |
|---|---|---|---|---|---|
| 4.1 | State·1 Decisions & open questions | Yes, `renderDecisions` `:1509-1539` | Open Qs pinned top w/ options, footer "View-only — answer in the session itself. The tracker never writes to it." verbatim (`:1530-1531`), "Decided earlier" divider + closed list in secondary text — all match | MATCH | — |
| 4.2 | State·2 Pull requests | Yes, `renderPRs` `:1541-1559` | Filters to `p.created` only (excludes referenced, per doc); state badge open/merged/closed; `agent` tag — but **PR title is never rendered** (parser never captures one, `util.py:collect_prs` regex-only) — shows `#num · repo` instead of `number + title` | DRIFT (data gap, documented) | MED |
| 4.3 | State·3 **Links (NEW)** | Yes, `renderLinks` `:1561-1582`, `deriveLinks` `:487-529` | Two groups Generated/Worked, verbs `created/wrote/endpoint/read ×N/cited`, dedup+highest-privilege, footnote text verbatim, `localhost:*` drawn as included (open decision resolved as spec's default) — all present. Data source is a **best-effort regex URL scan** over narrative/requests/commands text, not a real "links" field from the parser (comment `:471-478` "REQUIRED ADDITION") | MATCH (behaviourally) / DRIFT (provenance is approximated, not a first-class field) | LOW |
| 4.4 | State·4 Session summary | Yes, `renderSummary` `:1584-1595` | Goal/Now/So far labels+body; `Now` styled `--text-thinking`/600 (`ext_cr_detail.css:804`) | MATCH | — |
| 4.5 | State·5 Plan on the go | Yes, `renderPlan` `:1597-1620` | `--surface-note` tint (`opts.tint="note"` `:860`), header "📝 PLAN ON THE GO · N notes", delivery chips exactly per `push_when` (turn/wake/none→copy), row actions copy/remove, dashed "Jot the next thing…" + push | MATCH | — |
| 4.6 | Evidence·1 Files | Yes, `renderFiles` `:1624-1640` | basename 500-weight not actually bolded separately (whole path rendered mono, no basename/dir split), `+N`/`−N`, `agent` tag, `md` tag, footer hint verbatim | DRIFT (no basename/dir visual split) | LOW |
| 4.7 | Evidence·2 Commands | Yes, `renderCommands` `:1642-1656` | 22px status gutter word ok/fail, header count "42 · 1 failing"; **doc's per-provider text "42 · status not recorded" for providers without exit status is never implemented** — no branch produces that string anywhere in the file | MISSING | MED |
| 4.8 | Evidence·3 Agents & shells | Yes, `renderAgentsPanel` `:1679-1740` | Running shown, "Show N finished", re-run grouping →`×N` tag opens latest (`groupAgentReruns` `:1663-1677`), Auggie degrade path uses the shared degraded-state component | MATCH | — |
| 4.9 | Evidence·4 Run a command | Yes, `renderRunPanel` `:1742-1749` | mono field + run button + constraint text verbatim | MATCH | — |
| 4.10 | Evidence·5 Terminal controls | Yes (markup), `renderTerminalPanel` `:1751-1772` | Copy/fields match spec exactly, BUT gated on `session.term_attached` (`:1757`) which **no provider or server route ever sets on the detail dict** — grep of the whole Python tree finds zero occurrences of `term_attached`, even though `GET /api/term/attached` exists (`term_vt.py:2650,3339`) and is simply never called from this file. Panel is therefore **permanently hidden** in the shipped app. | MISSING | HIGH |
| 4.11 | Panels not in spec | "Queue a note" header button/card (`:731,758-761`); Fork-lineage card treated as a 6th Evidence-column item; extra timeline pop-out ⤢ control | — | EXTRA | LOW |

## 5. README decision #7 — cards start collapsed, per-column Expand/Collapse

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 5.1 | Default state | Every panel starts collapsed except Conversation timeline | `Detail.prototype.update` `:1263-1264`: `var def = key === "timeline" ? false : defaultFolded();` — timeline forced open, every other panel defaults per `defaultFolded()` which returns `true` unless the Config "Cards start folded" pref (`cr.cardsFolded`) is explicitly `false` (`:226-232`) | MATCH | — |
| 5.2 | Per-panel persistence | localStorage per panel per session, default never-seen = collapsed | `getCollapsed`/`setCollapsed`/`panelKey` `:207-218` scoped by `sid`+panel key | MATCH | — |
| 5.3 | Expand all/Collapse all scope | PER COLUMN, not global | Click handler `:951-958` iterates only `STATE_PANELS` or `EVIDENCE_PANELS` per the clicked `data-col`; no global control exists in the skeleton | MATCH | — |
| 5.4 | Collapsed panel still shows header + count | e.g. "18", "42 · 1 failing" | `setPanelCount` used by every `render*` function even when collapsed (count is set unconditionally, not gated on expand state) | MATCH | — |
| 5.5 | Collapsed panel keeps state tint | Decisions stays `--surface-awaiting` tinted when open; Commands tints its **count** (not the whole panel) when failing | `renderDecisions:1514` toggles `crd-tint-awaiting` at wrap level (persists collapsed); `renderCommands:1649` toggles `crd-count-failing` on the count span only — matches doc's own "brick-tinted in its count" wording exactly | MATCH | — |

## 6. README decision #8 — one merged conversation timeline

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 6.1 | Single timeline, no separate Narration/Prompts panels | `mergeTimeline` (`:431-469`) folds requests+narrative+decisions+commands **+ files/reads/agents** (tool-call rows, beyond spec's four kinds — see 6.2) into one array, one panel `crd-timeline-panel` (`:885-916`) | MATCH (and extended) | — |
| 6.2 | Panel head: "▾ TIMELINE" + muted legend "prompts · narration · tools · results" + right-aligned all/talk-only pair | Implementation instead makes the four legend words **individually clickable filter chips** (`:894-900`) additive on top of all/talk (`timelineEntryVisible` `:2022-2032`), plus adds an unspec'd pop-out (⤢) button (`:906`) — a 7-control row vs. spec's static legend + 2-button pair, and required extra phone-only wrap CSS to avoid overflow (`ext_cr_detail.css:1284-1306`) | DRIFT (superset of spec) | LOW |
| 6.3 | Entry anatomy (prompt right-bubble, narration no-bubble, tool-call, command-result, ask-bubble, diagram, live entry) | `entryHtml` `:1825-1904` implements prompt/narration/ask/command/tool/diagram cases with the documented asymmetry (prompt gets `.crd-bubble-prompt`, narration is plain text) | MATCH | — |
| 6.4 | Newest-first vs. doc's implied order | Doc doesn't state timeline order explicitly, but "stuck to latest" behaviour is described as bottom-follow in a chat UI; impl sorts **newest-first** and treats "stuck" as top-of-scroll (`:922-926`, comment "defect 1" fix) | Ambiguous vs. doc | — | LOW |

## 7. README decision #9 — progress spine

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 7.1 | Spine exists, replaces ring + pill chain | `renderSpine` `:1434-1505`; no leftover progress-ring code anywhere — grep for `progress-ring`/`crd-ring` across `ext_cr_detail.js/css`/`ext_cr_boot.js` returns zero hits | MATCH | — |
| 7.2 | Header row "▾ PROGRESS SPINE" · "7 of 11 · 41m elapsed" · right hint | `:1437-1438`, hint text verbatim `:766-767`/`1490-1497` | MATCH | — |
| 7.3 | Segment widths time-proportional (real timestamps; unstarted share remainder equally) | `spineSegments` `:265-360` reproduces the doc's `spineWidths` algorithm: `usedPct = min(88, spentTotal/elapsedMs*100)`, per-active-todo share `spentByIdx[i]/spentTotal*usedPct`, pending split evenly over `100-usedPct`; falls back to an honest equal-width split (never fabricates precision) only when `started_at` is missing for any active todo (`hasTimes` check `:293-294`) — this fallback is undocumented in the spec's pseudocode but is the correct honest behaviour per the file's own header comment | MATCH (spec's formula reproduced faithfully; documented, sound fallback added) | — |
| 7.4 | MAX_USED 88%, floor 3%, group >16 into "N earlier" | `FLOOR=3, MAX_USED=88, GROUP_THRESHOLD=16` `:291`, grouping logic `:332-344` | MATCH | — |
| 7.5 | Segment content: Done (elapsed, omit <7%), Running (dot+RUNNING+elapsed+leading edge), Pending (dashed, empty) | `:1447-1462`; running segment redesigned to space-between layout per "drift 7" comment rather than doc's single string, but content (dot, word, elapsed, edge) all present | MATCH | — |
| 7.6 | Event gutter, 20px, real time offsets, 5 marker kinds (prompt/fail/ask/agent/now), ~2%-collision offset | `buildMarkers` `:362-402` implements all 5 kinds with correct glyphs/colors/titles; collision handling offsets by 2% not the doc's literal "10px" (`:393-396` — uses percentage nudge, not px) | DRIFT | LOW |
| 7.7 | Footer 3-part mono row | `:1477-1482`; "now" is literal word not a clock (matches doc's mock exactly per "drift 7" comment, doc's own body text says "now" too) | MATCH | — |
| 7.8 | Accessibility: `role="img"` + full aria-label summary | `role="img"` on `.crd-spine` (`:762`), `aria-label` built and set `:353-358,1500-1504`; segments are focusable `<button>` (`:1461`) | MATCH | — |

## 8. Decision panel must be view-only (non-negotiable)

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 8.1 | View-only copy present | "View-only — answer in the session itself. The tracker never writes to it." | Present verbatim in panel footer (`:1530-1531`) and in the timeline's ask-bubble (`:1877`, slightly reworded "answer in the session. The tracker never writes to it.") | MATCH (panel exact, timeline near-exact paraphrase) | — |
| 8.2 | No write path | `renderDecisions` (`:1509-1539`) emits no buttons, no `data-act` handlers, no `fetch`/POST anywhere in the function or its markup; only read-only rows and the footer note | MATCH | — |

## 9. Phone layout — 390pt

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 9.1 | Fixed bottom bar: note field + 48px send + 48px stop | `crd-phonebar` skeleton (`:805-810`), CSS `:1197-1245` (48×48 circular, `display:flex` only at ≤480px `:1281`) | MATCH | — |
| 9.2 | Progress spine compressed: bar + event gutter only, no per-segment labels | `ext_cr_detail.css:1276-1279` hides `.crd-spine-hint`, `.crd-seg-elapsed`, `.crd-seg-running-elapsed` at ≤480px | MATCH | — |
| 9.3 | Chat timeline, folded State/Evidence cards | Reuses desktop timeline/panel markup reflowed via `order` (§3.4) — panels already collapsed-by-default (§5.1) so folded-by-default holds on phone too | MATCH | — |
| 9.4 | Status bar → back chevron + ellipsed breadcrumb + "7/11" | `ext_cr_detail.css:1271` `.crd-backline { display: none; }` — the desktop back-line (with its own different content) is simply **hidden**, no phone-specific breadcrumb/counter header is built anywhere (grep for "breadcrumb"/"7/11" in js/css: zero hits) | MISSING | MED |
| 9.5 | 34px presence orb + "Claude is thinking" + current file | No matching markup/class anywhere (grep for "presence orb"/"thinking" as UI text/"crd-presence": zero hits — only unrelated `--text-thinking` token usages) | MISSING | MED |
| 9.6 | "Live narration at 21px serif" as its own phone element | Not implemented as a distinct element; `.crd-goal` (the desktop header's goal line) is set to 21px serif at ≤480px (`ext_cr_detail.css:1275`), which is a different field (session goal, not live narration text) | DRIFT/MISSING | MED |
| 9.7 | Awaiting question card (standalone, above folded cards) | Not implemented as a distinct phone element — the "ask" bubble only exists inside the merged timeline (§6.3), not pulled out as a standalone phone card | MISSING | LOW |
| 9.8 | All hit targets ≥44px | `ext_cr_detail.css:1314-1366` ("BLOCKER 2") explicitly pads icon buttons, panel headers, and every dense row to 44px min via `::before` overlays / `min-height` | MATCH | — |

**Net for area 9: the bottom bar and 44px/spine-compression rules are honored, but the phone-specific *header* redesign (presence orb, "Claude is thinking", current file, 21px live-narration line, breadcrumb+counter, standalone awaiting-question card) described in the doc's phone Detail-screen structure is not built — the desktop header/back-line is reflowed/hidden instead.**

## 10. Provider degradation

| # | Panel | Claude path | Auggie path | Verdict | Severity |
|---|---|---|---|---|---|
| 10.1 | Conversation timeline | Full narration/tools shown | `providerNote()` (`:1781-1788`) reads `CR.dialogs.providerNoteFor(meta.source)`; `narrDegraded` explicitly excludes Auggie (`:1799` "Auggie's own `ok` field says Full narration/todos/files/commands") — only true for Augment-extension sources; degraded panel shows honest explanation + hides filter row (`:1800-1811`) matching spec's "Degraded providers" section | MATCH | — |
| 10.2 | Agents & shells | Populated from `agents_bg`/`shells` | Auggie's parser always sets `"agents_bg": []` (`auggie.py:563`) — real absence, not a bug; panel shows a distinct **degraded** card ("No background-work model — capability shows empty-because-it-cannot-exist, not broken") rather than the generic empty state (`:1723-1737`) | MATCH | — |
| 10.3 | Terminal controls | Gated on `term_attached`, never set by claude.py either | Same — never set by any provider | MATCH (both equally never render — see 4.10) | — (rolled into 4.10 HIGH) |
| 10.4 | Commands "status not recorded" | Claude's `commands[].ok` always real | Auggie **does** carry real `ok`/error status (`auggie.py:499,680` — annotated from an error map), so the doc's premise that Auggie lacks exit status appears **factually stale**; regardless, no code path anywhere produces the "status not recorded" string for any provider | DRIFT / spec-premise mismatch | MED |
| 10.5 | Links panel | `prs`/`files`/text-scan present for Claude | Auggie emits `prs` (`:568`) and has file/narrative text for the same regex scan — `deriveLinks` operates on the shared shape, no per-provider fork | MATCH | — |
| 10.6 | Session summary / Plan | `overview`/`notes`/`push_when` present for both | Auggie: `overview` `:580`, `notes` `:590`, `push_when(False,0,0)` `:593` (Auggie has no hook, so always "copy it" chip per doc's own delivery-chip table) — `renderPlan`'s chip logic (`:1600-1603`) correctly maps `push_when==="none"` → "queued · copy it" | MATCH | — |
| 10.7 | Effort chip in Terminal controls | Claude has `meta.effort` | Auggie explicitly omits `effort` (`auggie.py:551` "no 'effort' key here — Auggie logs have no reasoning-effort concept") — `renderTerminalPanel` falls back to `meta.effort || "—"` (`:1766`), degrades honestly | MATCH | — |

---

## Fix list (ordered by severity)

**HIGH**
1. `ext_cr_detail.js:1757` — Terminal controls panel is permanently hidden because `session.term_attached` is never set. Wire a call to the existing `GET /api/term/attached?tty=<id>` route (`term_vt.py:2650`) keyed by the session's tty, or add the field to the shared detail-dict seam server-side, so the panel can ever render.
2. `ext_cr_detail.js:1306-1327` (and skeleton `:637-646` comment) — restore the spec's Row-3 stat-chip strip (`files/commands/reads/commits/tests/tokens/branch`) with the `--`/`N/A` missing-data convention; it was deliberately dropped, contradicting the doc which is authoritative.

**MED**
3. `ext_cr_detail.js:1292-1304` + `ext_cr_boot.js:903` — pass a `triage` object (`{index,total}`) into `CR.detail.update()`'s state so the back-line hint ("N of M needing attention · j / k") can ever render.
4. `ext_cr_detail.js:1352-1355` — `session.pinned` is missing from `parse_any()`'s detail dict (`registry.py:70-72` only puts it on the list dict); merge it into the per-session detail shape so the header's Pinned pill can ever show.
5. `ext_cr_detail.js:1642-1656` — implement the doc's "42 · status not recorded" header text for providers lacking real exit-status data (and re-verify whether Auggie is actually the right target, since `auggie.py:499` shows it does carry `ok`).
6. `ext_cr_detail.js:726-733` — split header actions back into the spec's two stacked rows (Search/Flag pills with visible labels; Open terminal/Resume here/External on a second row), or update the doc if the single-row layout is an intentional, approved change.
7. Phone layout (`ext_cr_detail.css` ≤480px block) — build the spec's phone-specific Detail header (34px presence orb + "Claude is thinking" + current file, back chevron + breadcrumb + "N/M" counter, standalone 21px-serif live-narration line, standalone awaiting-question card) instead of hiding/reflowing the desktop header.

**LOW**
8. `ext_cr_detail.js:730` — change button copy from "Resume" to "Resume here".
9. `ext_cr_detail.js:894-908` — the timeline's four filter chips + pop-out button exceed the doc's static-legend + all/talk-only spec; confirm with the doc owner or trim back to spec.
10. `ext_cr_detail.js:393-396` — event-gutter collision offset uses a 2% nudge, not the doc's literal "10px"; convert to a px-based offset to match spec exactly.
11. `ext_cr_detail.js:1624-1640` — Files panel doesn't visually distinguish the basename (500 weight) from the rest of the path, as the doc specifies.
