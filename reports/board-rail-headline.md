# Job-summary headline on Board cards and the session rail

Branch: `board-rail-headline` (worktree `.claude/worktrees/job-summary-header`), base `personal/main` @ ca76ba1.
Builds on `reports/job-summary-header.md` (the session-detail `headline` + `HEADER_LINE` config, landed in ee25e22/2315584/ca76ba1).

## Contract (verbatim)

> can we please have the summary header in the board room view when each session is a card (session card) and the summary header into the 2nd line in the session sidepanel as well, both in the boardroom view and also in the classic dashboard view

(Screenshot: the Control Room Board view — tiles show state, title, project/source line, a goal/prompt line, a progress bar; the left rail "Sessions — newest first" rows show title, then a meta line `Agent · 4/5 · dw-vida-stack · claude cli · just now · 3 running`, then cwd · model.)

| # | Clause | Status |
|---|---|---|
| R1 | Board view: each session card shows the summary headline | discharged — final review fixes applied (tests: test_list_headline.*; test_list_headline_ui.CrHeadlineRenderTests awaiting/covers_needs/working tile tests) |
| R2 | Session side panel (rail), Board/Control Room view: summary headline as the row's 2nd line | discharged — final review fixes applied (tests: CrHeadlineRenderTests rail order/pill/narration-safe) |
| R3 | Session side panel, classic dashboard view: summary headline as the row's 2nd line | discharged — final review fixes applied (tests: ClassicHeadlineRowTests order/url/auggie-null) |
| R4 | Same `HEADER_LINE` policy (summary default / narration) as the header — server-owned | discharged — final review fixes applied (tests: ListHeadlineTests.test_narration_mode_ignores_job, test_list_and_detail_agree_on_job_row, ListHeadlineHttpTests.test_http_list_headline_and_live_flip) |
| P1 | Pipeline: opus plan → opus review → plan revised → sonnet implement → opus final review → fix all → /tracker-gap discipline → /tracker-push | discharged — pipeline completed, fixes CF1-CF2/SF1-SF4 applied |

## Plan

Author: opus planner, 2026-11-13, at `ca76ba1`. **Revision 2 (2026-11-13).** This revision folds in the
review's accepted fixes F1–F4 and F6, scoped as the orchestrator's verdict table says. F5 is cut. Every
`path:line` below was read in this worktree. Line numbers drift, so re-read the region before editing
(conventions rule 12).

This builds on the detail-header work (`reports/job-summary-header.md` §A). The only new pieces are:
- a one-pass job index;
- a list-row headline built by the **same** `overview.headline()`;
- a seam de-duplication so the tile line beneath the headline never repeats it;
- three renderers.

### 0. Facts measured for this plan (read-only, real data, 2026-11-13)

**Endpoints and size**
- **One list endpoint feeds everything.** `/api/list` → `registry.all_sessions()` (`server.py:385-407`). It is polled
  every 5 s by `setInterval(loadSide,5000)` (`app.js:1449`). The CR board tiles, the CR rail and the classic sidebar
  all render from that one payload. The board does **not** fetch anything richer per tile: a tile knows only the list dict.
- **Size.** The live server on :8790 returns 1006 rows, 909 KB, in 0.28 s. By source: augment-vscode 607,
  augment-cursor 111, claude-* 200 (`list_sessions(limit=200)`, `claude.py:821`), auggie 88. So about 290 rows can
  carry a headline. The ~720 Augment-ext rows have no narration source (`augment_ext.py:185-189`, LevelDB).

**Narration**
- Narration is already cached per row, for free.
  - Claude: `_session_meta()` is mtime-cached (`claude.py:247`) and already holds `last_text`. That is the newest
    assistant text in the 96 KB tail, cut to `t[:200]`, skipping `<` echoes (`claude.py:195-197, 298`). Today it only
    feeds the live `now_line` (`claude.py:915-916`) and is never sent to the client.
  - Auggie: the `_AUGGIE_LIST_CACHE` entry holds the same thing, also cut to 200 (`auggie.py:140-153, 343`).
  - On real data, 192 of the top 200 Claude rows have a non-empty `last_text`. 206 Claude `last_text` values are
    exactly 200 chars, so the narration clip happens upstream (see F3).

**Jobs**
- `~/.claude/jobs` has 148 dirs and 114 `state.json` files (314 KB), covering 127 distinct session ids.
- 60 of the 200 listed Claude rows have a job, and all 60 have a non-empty `detail`.
- The live roster holds 7 shorts. Band × live: blocked/dead 62, done/dead 54, working/dead 5, working/live 4,
  done/live 1, blocked/live 1. **So the dead-job pill gating matters on lists: 67 non-done dead jobs.**
- Of the 53 blocked jobs:
  - 38 have a `detail` that differs from `needs`, so the headline is *not* the question.
  - 14 have `detail == needs` after whitespace is flattened, and 1 has an empty `detail` (the headline then falls back
    to `needs`).
  - Showing `needs` under the headline would therefore repeat the question on 15 of 53 (see §3a `covers_needs`).

**Cost**
- Calling `job_for(sid, live)` once per row is **not** viable. A miss (any non-job row) costs about 5 ms: a listdir plus
  about 114 `file_pass` stats and unpickles (`claude.py:792-804`). Over 140 non-job rows that adds about 0.7 s per poll.
- A one-time index over the same `file_pass("claude.jobstate", …)` cache costs 1.1–1.4 ms median warm and ≤4 ms p95.
  An uncached raw parse of all 114 files takes 7–35 ms. The review found the index equals `job_for` for all 127 sids.
- The roster read (`_live_daemon_shorts`, `claude.py:594`) costs about 1.2 ms. It is already paid once per poll inside
  `_blocked_jobs()` (`claude.py:720-744`, called at `:825`).

**CSS and today's lines**
- **CSS scope.** `#nextRoot` has `class="tracker-next cr"` (`index.html:229`). So the detail's pill rules
  `.cr .crd-hl-band` / `.crd-hl-blocked|working|failed` (`ext_cr_detail.css:237-244`) **already apply** to board
  tiles and rail rows. The classic pill is `.hlband.hl-*` (`app.css:402-405`).
- **Tile today.** `tileLine()` (`ext_cr_board.js:2825-2832`):
  - an awaiting tile shows `needs || prompt` (the owner's "leave awaiting alone" ruling, `:2822-2823`);
  - every other state shows `now_line` when live, and no line otherwise.
  - `sessionTile` pushes the result at `:2885-2886`.
  - `now_line` has exactly one client reader, `tileLine` (`:2829-2830`).
- **CR rail row today.** `railRow()` (`ext_cr_board.js:1909-2183`) stacks `.cr-rail-r1` (`:2130`), then
  `.cr-rail-meta` (`:2157`), then `.cr-rail-dir` (`:2180`). The row is a keyboard target: `tabindex=0`, and Enter →
  `openSession` (`:2110-2116`). The same `railRow` renders the Sessions destination (`:1817`, `rich`).
- **Classic row today.** `sessionRow()` (`app.js:1177-1229`) stacks `.srow1`, then `.smeta`.
- **Search rows are out of scope and unchanged.** Rail and classic search-mode rows use a separate shape
  (`decorateSearchHits` `ext_cr_board.js:1683-1703` builds a fresh object with no `headline`; the `renderSide` search
  branch is at `app.js:1093-1104`).
- **`md()` turns bare URLs into links** (`app.js:157-161`). Job details and narration are full of PR URLs.

**Names**
- Names to avoid: a global `hl(text,q)` (`app.js:1058`) and local `shl` vars (`app.js:1982`).
- New names below are grep-clean: `job_index`, `_job_shape`, `list_headline`, `covers_needs`, `hlHtml`, `headlineEl`,
  `.shline`, `.cr-rail-hl`, `.cr-tile-line--hl`.

### 1. Server: one job index per list call (`aitracker/providers/claude.py`)

**1a. Factor the shape out of `job_for`** (`claude.py:774-817`). This makes the list and the detail agree on band,
label and live gating **by construction**. The tail of `job_for` (`:810-817`) moves into:
```python
def _job_shape(short, f, live):
    """The header job shape for one parsed state.json (f = _job_fields) found under dir `short`.
    A non-"done" band whose job dir isn't live loses its pill; text always stays."""
    band = _job_band(f)
    label = BAND_LABEL[band]
    if band != "done" and short not in live:
        band = label = None
    elif f["state"] in ("failed", "stopped"):
        label += " · " + f["state"]
    return {"band": band, "label": label, "detail": f["detail"], "needs": f["needs"],
            "result": f["result"], "state": f["state"], "updated": f["updated"] or None}
```
`job_for` now ends with `return _job_shape(short, f, live)`. Nothing else changes, and the detail path is byte-identical.

**1b. New `job_index(live)`** beside it:
```python
def job_index(live):
    """{session id: job shape} for EVERY job, from ONE listdir of JOBS_DIR. Same file_pass cache and
    the same precedence as job_for: the job whose dir == sid[:8] wins, else the first dir in sorted
    order whose sessionId/resumeSessionId is sid. For the session LIST, where a per-row
    job_for() miss (a full scan) would cost ~5 ms x every non-job row. Never raises."""
    root, hits = config.JOBS_DIR, {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return {}
    for short in names:
        if not safe_path_component(short):
            continue
        try:
            f = file_pass("claude.jobstate", os.path.join(root, short, "state.json"), _job_fields)
        except (OSError, ValueError):
            continue
        for sid in (f or {}).get("ids", ()):
            if sid not in hits or sid[:8] == short:      # direct dir beats an earlier resume match
                hits[sid] = (short, f)
    return {sid: _job_shape(short, f, live) for sid, (short, f) in hits.items()}
```
The prefix-collision rule still holds: ids are taken only from the file's own `ids`.

**1c. `list_sessions()`** (`claude.py:821-967`). Next to `blocked = _blocked_jobs()` (`:825`), add
`jobs = job_index(_live_daemon_shorts())`. That is a second roster read (~1.2 ms); `_blocked_jobs` stays untouched.
In the `out.append({...})` dict (`:920-959`), add two **raw facts**. The seam turns them into the headline and then drops them (§3b):
```python
            "job": jobs.get(sid),                    # header job shape or None (seam -> headline, then dropped)
            "last_text": sm.get("last_text") or "",  # newest tail narration (same cached tail read)
```
`list_sessions()`'s own `now_line` and `needs` are **unchanged**. The selfcheck asserts on them stay as they are
(`test_selfcheck.py:1005, 1009, 1051, 1072`).

### 2. Auggie: expose the narration it already has (`aitracker/providers/auggie.py`)

In `list_auggie()`'s `out.append({...})` (`auggie.py:370-385`), add `"last_text": e.get("last_text") or "",`. Auggie
has no job concept, so `job` is absent (treated as None).

Augment-ext (`augment_ext.py:165-210`) gets **no change**. It has no narration and no job, so its headline is None and
it keeps today's lines.

### 3. The shared seam (`aitracker/overview.py` + `aitracker/registry.py`)

**3a. `overview.py`**, directly after `headline()` (`overview.py:7-19`, which is unchanged):
```python
LIST_HL_MAX = 200   # one-line rows / 2-line tiles; keeps /api/list's added payload ~10%

def list_headline(s, mode):
    """A session-LIST row's headline: headline() itself over the row's cheap facts (the job index
    entry + the cached tail narration). Same policy and the same keys as the detail header,
    flattened to one line and clipped, plus covers_needs: True when the text already says the
    blocked job's question, so a tile need not repeat it. None when there is nothing to say."""
    job = s.get("job") or {}
    hl = headline({"job": job, "message": s.get("last_text") or ""}, mode)
    if hl["source"] == "none":
        return None
    t = " ".join(hl["text"].split())
    hl["text"] = t if len(t) <= LIST_HL_MAX else t[:LIST_HL_MAX - 1].rstrip() + "…"
    q = " ".join((job.get("needs") or "").split())[:100]
    hl["covers_needs"] = bool(q) and hl["source"] == "job" and q in hl["text"]
    return hl
```
- `headline()` already falls back to `d["message"]` when there is no `narrative` (`overview.py:16-17`), so it is called
  unmodified. **One policy function, two inputs.**
- In practice the clip only fires on job text, which is up to 400 chars (`claude.py:768`). Narration arrives at ≤200
  already, so for narration the function only flattens.
- **Why `covers_needs` is server-side.** The obvious server fix, blanking a duplicate `needs` on the row, is ruled out:
  the selfcheck asserts the question survives on the row of a needs-only job (`test_selfcheck.py:995-1005`, a job with no
  `detail`, whose headline therefore *is* `needs`). A client-side string match is also ruled out, because the client would
  be comparing `now_phrase`'s 60-char truncation against the headline (conventions rule 5).

**3b. `registry.all_sessions()`.** Before the per-row loop (`registry.py:89`), read `mode = config.HEADER_LINE` once.
Inside the loop, after `agent_map_n` (`:115`), add:
```python
        # The headline the detail header shows (job summary / narration, config HEADER_LINE), from the
        # row's cheap facts. A live row's now_line that merely repeats the headline's narration is
        # blanked so a tile never says the same sentence twice (structural ⚙/▶/⧖ phrases stay).
        # Raw inputs are then dropped so the wire doesn't carry the same text twice.
        lt = s.get("last_text") or ""
        s["headline"] = list_headline(s, mode)
        if s["headline"] and s["headline"]["source"] == "narration" and lt and s.get("now_line") == now_phrase(lt):
            s["now_line"] = ""
        s.pop("job", None)
        s.pop("last_text", None)
```
Imports, each staying one line (bundle.py note at `registry.py:6-8`):
- `from .util import …` (`registry.py:13`) gains `now_phrase`;
- `from .overview import empty_heartbeat, headline` (`registry.py:14`) gains `list_headline`.

The de-duplication holds for both providers. Claude's narration `now_line` is `now_phrase(sm["last_text"])`
(`claude.py:916`) and Auggie's is `now_phrase(e["last_text"])` (`auggie.py:369`), so equality is exact.
`HEADER_LINE` is read **at call time**, so a Config flip reaches every open page on its next list poll (≤5 s), the same
as the header.

**3c. JSON shape: reuse the detail shape plus one list-only key.** Each `/api/list` row gains:
```
"headline": null | {
  "mode": "summary" | "narration",
  "source": "job" | "narration",
  "text": str,              // ≤200 chars, one line
  "band": "blocked" | "working" | "done" | null,
  "label": str | null,
  "state": str | null,
  "updated": str | null,
  "covers_needs": bool
}
```
- **Why the detail shape:** it is the shared `headline()` output, so the list and the detail can be diffed and
  rendered the same way. A slim subset would save only about 9 KB per poll.
- **`null` instead of `source:"none"`:** saves about 90 B on each of about 720 Augment-ext rows, and gives the
  renderers a single falsy check.
- **`covers_needs`** is the only list-only key (§3a).
- A live row's `now_line` may now be `""` on the wire (§3b), but only when it duplicated the headline.

**3d. Payload and per-poll cost.**
- **Payload:** about +100 KB on 909 KB (~11%; the review measured +99.5 KB, 271 rows with a headline).
- **Server time:** one job-index build (~1.2 ms warm, ≤35 ms after a pass-cache eviction), one roster read
  (~1.2 ms), and about 290 `split`/`join` plus `now_phrase` calls (<1 ms).
- **No new file reads for narration.**

### 4. Render: classic sidebar (R3), `aitracker/web/app.js` + `app.css`

- **One HTML helper**, next to `paintHeadline` (`app.js:2307-2311`), shared by the header and the rows:
  ```js
  // the server's headline -> band pill + inline-md text; no policy here (server owns mode/text/label).
  // inline=true (session rows): anchors unwrapped -- a row is one click/Enter target, no inner tab stops.
  function hlHtml(hl,inline){let t=md(hl.text||"");if(inline)t=t.replace(/<a [^>]*>([\s\S]*?)<\/a>/g,"$1");return (hl.label?'<span class="hlband hl-'+esc(hl.band||"")+(hl.state==="failed"?" hl-failed":"")+'">'+esc(hl.label)+'</span> ':'')+t;}
  ```
  `paintHeadline` becomes `$("ov_hl").innerHTML=hlHtml(hl);`. The header keeps real links, and its output is unchanged
  (the existing `test_classic_overview_renders_headline` proves it). `md()` itself is untouched.
- **`sessionRow()`** (`app.js:1223-1228`): between the `.srow1` div's close and `<div class=smeta>`, insert
  `${s.headline?'<div class=shline>'+hlHtml(s.headline,true)+'</div>':''}`. Agent child rows get it too (same function).
  Search-mode rows are not touched. The classic row has no "now" line, so the F1 de-duplication does not apply here.
- **`app.css`**, next to `.smeta` (`app.css:136`):
  ```css
  .shline{font-size:12px;line-height:1.4;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:-4px 0 6px;min-width:0}
  .shline .hlband{padding:1px 6px;font-size:10px;vertical-align:0}
  ```
  There is no anchor rule: there are no anchors (F2). Nothing is gated by host or viewport. `.side` is 260 px on tablet
  (`app.css:553`) and an 86vw drawer on phone (`app.css:555-`); the ellipsis handles both.

### 5. Render: Control Room rail (R2) and board tiles (R1), `aitracker/web/ext_cr_board.js` + `.css`

**One DOM helper** inside `createBoard()`, next to `tileLine` (`ext_cr_board.js:2825`):
```js
// The server's headline as one element: pill (the detail header's own .crd-hl-band classes,
// which apply under #nextRoot.cr) + inline md text with anchors unwrapped (a rail row / tile is a
// single click+Enter target -- no inner tab stops). Renders; decides nothing. null -> null.
function headlineEl(hl, cls) {
  if (!hl || !hl.text) return null;
  var pill = hl.label ? '<span class="crd-hl-band crd-hl-' + esc(hl.band || '') +
    (hl.state === 'failed' ? ' crd-hl-failed' : '') + '">' + esc(hl.label) + '</span> ' : '';
  var body = (typeof md === 'function' ? md(hl.text) : esc(hl.text)).replace(/<a [^>]*>([\s\S]*?)<\/a>/g, '$1');
  return h('div', { class: cls, title: (hl.label ? hl.label + ' · ' : '') + hl.text, html: pill + body });
}
```
- `h()` supports `html:` (`:784`). `title` goes through `setAttribute`, so it is safe.
- `md` is app.js's global (one script tag). It escapes first (`app.js:143-144`), so unwrapping its own `<a …>` leaves
  only escaped text.

**Rail (R2).** In `railRow()`'s child list, between `.cr-rail-r1` (`:2130`, closes before `:2157`) and `.cr-rail-meta`
(`:2157`), insert `headlineEl(s.headline, 'cr-rail-hl'),`. `h()` skips a null child (`:789`). The Sessions destination
gets it for free (same `railRow`, `:1817`).

**Tile (R1), per F1.** The headline goes first, and today's structural line stays beneath it. `tileLine(s, state)`
(`:2825-2832`) now returns an **array**:
```js
function tileLine(s, state) {
  var hl = headlineEl(s.headline, 'cr-tile-line cr-tile-line--hl');
  if (!hl) {                                            // today's exact branches, unchanged
    if (state === 'awaiting') return [h('div', { class: 'cr-tile-line' }, [s.needs || s.prompt || ''])];
    var nowLine = (typeof s.now_line === 'string') ? s.now_line.trim() : '';
    return [nowLine ? h('div', { class: 'cr-tile-line cr-tile-line--now' }, [nowLine]) : null];
  }
  var sub = (state === 'awaiting')
    ? ((s.needs && !s.headline.covers_needs) ? '⧖ ' + s.needs : '')   // the waiting question stays
    : ((typeof s.now_line === 'string') ? s.now_line.trim() : '');          // server already de-duplicated
  return [hl, sub ? h('div', { class: 'cr-tile-line cr-tile-line--now' }, [sub]) : null];
}
```
- `sessionTile` (`:2885-2886`) becomes `tileLine(s, state).forEach(function (el) { if (el) body.push(el); });`.
  The hero tile uses the same path. Group tiles (`agentGroupTile`) are untouched.
- An awaiting tile with a headline drops the first `prompt` from view; it stays in the tile tooltip (`:2852`).
- An awaiting tile with no headline is exactly today's tile.

**`ext_cr_board.css`**, next to `.cr-rail-dir` (`:977-984`):
```css
.tracker-next .cr-rail-hl { display:block; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  font: var(--fw-body) 12px/1.4 var(--font-sans); color: var(--text-secondary); }
.tracker-next .cr-rail-hl .crd-hl-band { padding: 1px 6px; font-size: 10px; vertical-align: 0; }
```
- There is no anchor rule (F2).
- The tile headline keeps the base `.cr-tile-line` 2-line clamp (`:1682-1691`). The sub-line keeps `.cr-tile-line--now`'s
  one-line ellipsis (`:1704-1713`). The flagged tile's amber panel (`:1692`) styles both.
- `grid-auto-rows:min-content` (`:1460`) means the taller tile cannot clip.
- No board media rule hides rail rows or tile lines, and the phone rail drawer is toggled by class, in-tree (`:1085-1100`).
  So both lines show at 390, 768 and 1280 px.

**Config wording** (`ext_cr_dialogs.js:1333`): the help text becomes "What the session's one-line status shows, in the
header, on board cards and in both session lists: …" with the rest unchanged. The `config.py:263` comment becomes
"the session line (header, board, rails); read live per request".

### 6. Sequencing

Each step leaves `make check` green. Prefix `make check` and every commit with `unset TRACKER_AUTH;`.

1. **Server (§1–3)** with the Python half of `tests/test_list_headline.py`. The SPA ignores the new key and a blanked
   duplicate `now_line` only removes a repeated sentence, so no tile loses a line yet.
   - **Wait:** until step 3 lands, a live narration-only tile shows no line. Steps 1 and 3 therefore ship in **one
     commit series pushed together**; never push step 1 alone.
2. **Classic (§4).** This is the smallest renderer and proves the shape end to end. Add the classic node tests.
3. **CR rail and tiles (§5)**, the CR node tests, and the dialog/config wording.
4. **End-to-end check.**
   - Run `make check`.
   - Restart a **test** server on a free port (never `pkill -f aitracker`).
   - Run `curl /api/list | python -c` and show: a live job row, a dead job (label null, text kept), a non-job narration
     row whose `now_line` was blanked, a bg-agent row whose `⚙` `now_line` was kept, an Auggie row, and an Augment-ext
     `null`.
   - POST `HEADER_LINE=narration` to `/api/config` and show the job row switch with no restart.
   - Open the page at 390 / 768 / 1280 px, and check the pill inside the 2-line tile clamp.
5. Run `/branch-sync`, re-run the gate, and push `board-rail-headline` to `personal`.

### 7. Tests (the nine assertions name both providers where the capability spans them)

**`tests/test_list_headline.py`** (new). It reuses `_Base`, `_write` and `_write_roster` from `tests/test_job_headline.py`.

*Job rows*
- `test_job_row_summary_live`: live roster, a `tempo:"active"` job. The `all_sessions()` row has
  `headline.source=="job"`, `text==detail`, `label=="Working"` and `band=="working"`.
- `test_dead_blocked_job_row_keeps_text_drops_pill`: empty roster, `tempo:"blocked"`. Text kept; `label is None`;
  `band is None`.
- `test_dead_done_job_keeps_completed`: `state:"done"` with an empty roster gives `label=="Completed"`, and
  `"failed"` gives `"Completed · failed"`.
- `test_resume_session_id_row`: job dir `zzzz9999` with `resumeSessionId==SID` is found.
- `test_prefix_collision_not_borrowed`: dir `SID[:8]` whose `sessionId` is a stranger gives narration, not job.
- `test_index_agrees_with_job_for`: a fixture of 4 jobs (direct, resume-only, a collision, two dirs claiming one sid).
  For every sid, `C.job_index(live).get(sid) == C.job_for(sid, live)`.
- `test_one_listdir_per_list_call`: patch `mock.patch.object(C.os, "listdir", wraps=os.listdir)`, with 3 non-job
  sessions. After `list_sessions()`, the number of calls with `config.JOBS_DIR` is **1**. This goes red under per-row
  `job_for`.

*Clipping and flattening (F3)*
- `test_job_detail_clipped`: a job with `detail = "word " * 100` gives `len(text) == 200` and `text.endswith("…")`.
  Red if the clip line is reverted.
- `test_narration_flattened`: narration `"line one\nline two"` gives `source=="narration"`, no `"\n"` in the text,
  `len(text) <= 200`, and `label is None`. Red if the `" ".join(split())` is removed.

*Other row kinds*
- `test_no_narration_row_is_null`: a transcript with only a user line gives `headline is None`.
- `test_narration_mode_ignores_job`: with `config.HEADER_LINE="narration"`, a job row shows its narration text and
  `label is None`.
- `test_auggie_row_narration`: an Auggie fixture (same shape as `test_job_headline.py:160-180`). Its `all_sessions()`
  row has `source=="narration"`, text equal to the last `response_text`, and `band is None`.
- `test_list_headline_pure_none`: `overview.list_headline({}, "summary") is None` (the Augment-ext / any-provider default).

*Seam de-duplication (F1)*
- `test_live_narration_now_line_blanked_on_wire` (Claude): a **live** non-job row with narration and no bg, todo or
  waiting. `all_sessions()` gives `now_line == ""`, while `list_sessions()` for the same id gives `now_line != ""`.
- `test_live_bg_now_line_kept` (Claude): a live row with an in-transcript running background agent (same fixture shape
  as `tests/test_cr_board_working_bg.py`). `all_sessions()` `now_line` starts with `"⚙"`, and `headline` is non-null.
- `test_auggie_now_line_dedupe`: a live Auggie row with narration only gives `now_line == ""`. A live Auggie row with an
  in-progress todo keeps `now_line` starting with `"▶"`.
- `test_covers_needs`: a live blocked job with `detail == needs` gives `covers_needs is True`. One with
  `detail != needs` gives `False`. A needs-only job (no `detail`, the selfcheck's own shape) gives `True` while
  `row["needs"]` still contains the question.

*Wire shape and HTTP*
- `test_raw_inputs_not_on_wire`: no `all_sessions()` row has the key `job` or `last_text`.
- `test_list_and_detail_agree_on_job_row`: `label/band/state/text` on the list row equal `parse_any(sid)["headline"]`.
- `ListHeadlineHttpTests(_ServerCase).test_http_list_headline_and_live_flip`: the `/api/list` row carries the job
  headline; after POST `HEADER_LINE=narration`, the next `/api/list` row is narration, with no restart.

**`tests/test_selfcheck.py`**: add one assertion next to the `all_sessions()` byid block (`:549`). It checks that the
Claude fixture row's `headline["source"] in ("job","narration")` and the Auggie fixture row's
`headline["source"]=="narration"`, both in one assert message. If no Auggie row reaches `all_sessions()` there, place it
next to the `_nw_by` block (`:983-991`), which has both `nwsess` and `auggie:nwaug`.

**`tests/test_list_headline_ui.py`** (new, node). It drives the **real** renderers and never greps the source.

*CR rail and tiles*
- These run through `window.CR.board.mount()/update()` with the DOM stub from `tests/test_cr_rail_polish.py:145-310`
  (`makeReal`, `allTextIn`; the stub records `innerHTML` for `html:`).
- Sessions:
  - a job row: `label:"Needs input"`, `band:"blocked"`, `covers_needs:false`, `needs:"provide a username"`, awaiting;
  - a narration row with text `"**bold** <img src=x> opened https://github.com/o/r/pull/7"`;
  - a headline row with `now_line:"⚙ 2 background agents"`, working;
  - a job row with `covers_needs:true` and `needs` set, awaiting;
  - a `headline:null` working row with `now_line:"⚙ 1 background agent"`;
  - a `headline:null` awaiting row with `needs:"login required"`.
- Assertions:
  - The rail row's children run in the order `cr-rail-r1` → `cr-rail-hl` → `cr-rail-meta`.
  - `cr-rail-hl` innerHTML starts with `<span class="crd-hl-band crd-hl-blocked">Needs input</span> `.
  - The narration row has `<strong>bold</strong>` and `&lt;img`, no raw `<img`, **no `<a `**, and does contain
    `https://github.com/o/r/pull/7` (F2).
  - A null-headline row has **no** `cr-rail-hl`.
  - The awaiting job tile shows **both** `cr-tile-line--hl` and a `cr-tile-line--now` reading `⧖ provide a username`.
  - The `covers_needs:true` tile shows only `cr-tile-line--hl`.
  - The working headline tile shows both `cr-tile-line--hl` and `⚙ 2 background agents` (F1).
  - The null tiles show exactly today's single line (`⚙ 1 background agent`; `login required`).
  - The Sessions destination (`rich`) row also has `cr-rail-hl`.

*Classic*
- Call `sessionRow()` as a global in the real bundle (the `tests/test_view_parity.py:114-230` pattern).
  - With a headline, the markup order is `srow1` → `<div class=shline><span class="hlband hl-blocked">Needs input</span> …`
    → `smeta`.
  - A URL headline gives **no `<a `** inside `shline`, with the URL text present.
  - The Auggie narration row has `shline` and no `hlband`.
  - `headline:null` gives no `shline`.
  - `paintHeadline` with the same URL still produces a real `<a ` (the header keeps its links).

*CSS (via `_extract_style_content`)*
- `.cr-rail-hl` and `.shline` each have `white-space:nowrap` plus `text-overflow:ellipsis`.
- **Every** `@media[^{]*\{…\}` body in the served styles (board breakpoints 480/600/1023/1279, `ext_cr_board.css:475,
  515,1248,1283,1442,1464,1467,1483,1805,1965`; classic 600/900) passes
  `assertNotRegex(body, r"(cr-rail-hl|shline|cr-tile-line--hl)[^{]*\{[^}]*display:\s*none")` (F4).
- The `.cr .crd-hl-band` rule exists, and `#nextRoot` carries class `cr` (guards the cross-file reuse).
- `assertNotRegex(page, r"location\.hostname[^;\n]*(headlineEl|hlHtml)")`.

**Red proof (before committing).** Revert each of these, confirm the named tests go red, then re-apply:
- §3b's `s["headline"] = …` line → the Python tests;
- the `now_line` blanking line → the two dedupe tests;
- `hl["covers_needs"] = …` → `test_covers_needs`;
- the `headlineEl(...)` child in `railRow` → the rail test;
- the tile's `sub` element → the F1 tile assertions;
- the anchor-unwrap `.replace` → the no-`<a` assertions;
- `${s.headline?…}` in `sessionRow` → the classic test.

### 8. Risky spots and fallbacks

1. **List narration can differ from detail narration in edge cases.** The list uses the tail's newest text (96 KB
   window). A single turn larger than 96 KB, or text the detail parser filters differently, gives an empty list
   headline (today's line stays) or slightly different text. Accepted. Job rows are identical by construction.
   Document it in the commit as a known gap.
2. **Payload (+~11%).** If the 5 s poll feels slow over the tunnel, lower `LIST_HL_MAX` to 120 (one constant), or pop
   `mode`/`updated` at the seam.
3. **Pass-cache eviction** (`util.py:669`, a 32 MB LRU). A burst of big transcript passes can evict the 114 tiny job
   entries; the next index build re-parses them once (≤35 ms). Every list call touches all of them, so they stay hot.
4. **Cross-file CSS reuse** (`.cr .crd-hl-band` lives in `ext_cr_detail.css`). If those rules were ever scoped tighter,
   board pills would go unstyled (the text still shows). The UI test asserts the selector. Fallback: move the 4 rules to
   `ext_cr.css`.
5. **Anchor unwrap regex.** It matches only `md()`'s own `<a href=… target=_blank rel=noopener>` output, and runs after
   escaping, so user text can't forge a tag. If `md()` ever emits nested markup inside a link, `[\s\S]*?` still keeps
   the inner text.
6. **One script tag** (memory: the gate misses load-time JS). A throw in `ext_cr_board.js` kills every file after it.
   The node tests run the real bundle, and step 4 opens the page after a restart.
7. **The `now_line` blanking is exact-match only.** If a provider ever builds its narration `now_line` differently from
   `now_phrase(last_text)`, the duplicate simply shows (cosmetic, nothing is lost). The dedupe tests pin both providers.
8. **Two roster reads per poll** (`_blocked_jobs` + `job_index`). For one poll they can disagree, which self-heals on the
   next. Accepted by the review.

### 9. Decisions the user may want to overrule

- **D1: resolved by F1, but it still needs your OK on one point.** Every card shows the headline, with the card's
  structural line kept beneath it:
  - the waiting question (`⧖ needs`) on awaiting cards, unless the headline already says it (`covers_needs`);
  - `now_line` ("⚙ 3 background agents", "▶ todo") on live cards.

  The server drops a `now_line` that only repeats the headline's narration. What changes on a card that has a
  headline: the awaiting card no longer shows the first **prompt**, which moves to the tooltip. This bends the earlier
  "leave awaiting alone" ruling (`ext_cr_board.js:2822-2823`), but only in that one respect: the question still shows,
  and a card with no headline is unchanged.
- **D2: non-job rows show narration even when idle.** Every row shows the tail's newest narration, live or not,
  matching the header (unlike `now_line`, it is not live-gated). The orchestrator confirmed this, since the contract asks
  for a 2nd line on every row. Alternative: live-gate it, which is quieter, cuts about 50 KB, and leaves idle rows with
  no 2nd line.

## Review

Reviewer: opus adversarial, 2026-11-13, at `ca76ba1`, read-only. Method: grep plus `sed` ranges on the cited
lines, and one in-process probe on real data (`/tmp/brh_review_probe.py`, which reimplements §1b verbatim and
calls the real `registry.all_sessions()`).

**Verified (no change needed):**
- **Index.** `job_index` median 1.12 ms, p95 1.77 ms, 127 sids. For every indexed sid, `job_index(live)[sid] == job_for(sid, live)` (0 mismatches on real `~/.claude/jobs`).
- **Payload.** +99.5 KB on 908.9 KB (10.9%). 271 rows carry a headline (60 from a job). The roster read costs 1.2 ms, not the ~7 ms the plan cites, so the cost claim is conservative.
- **Every cited symbol exists and does what the plan says:** `tileLine` 2825, `railRow` 1909 with r1/meta/dir at 2130/2157/2180, `h()` skips null children (789) and supports `html:`, `sessionRow` 1177, `paintHeadline` 2307, `_tail_scan` sets `last_text` (197), Auggie's cache sets it (343).
- **Raw keys.** No reader of `job` or `last_text` on list rows exists in `web/*.js`, so popping them breaks nothing.
- **`now_line` has exactly one client reader**, `tileLine` (`ext_cr_board.js:2829-2830`).
- **Search rows are safe.** `decorateSearchHits` (`:1683-1703`) builds a fresh object without `headline`, so `headlineEl` gets `undefined`, returns null, and adds no line. Classic's search branch is untouched.
- **Re-render is not new churn.** The rail already rebuilds every poll (`renderRail`: `railList.innerHTML=''`, scroll restored), and so does classic `renderSide`. There is no ETag or cache on `/api/list` (`server.py:385-407`), so headline changes propagate on the next 5 s poll (`app.js:1449`).
- **Layout.** `grid-auto-rows:min-content` (`ext_cr_board.css:1460`) means taller tiles cannot clip. The collapsed rail renders orbs, not `railRow`, so the new line never shows there.
- **Roster disagreement** (plan risk 7) self-heals within one poll. Accepted.

| # | Sev | Defect (file:line) | Repro: input → actual vs expected | FIX DIRECTION (change / must NOT change) | THE WAY | THE TEST (red before fix) |
|---|---|---|---|---|---|---|
| F1 | **High** | D1 as planned (§5 "Tile (R1)": `if (hl) return hl;` ahead of the old branches) **silently drops owner-ruled tile signals on every tile whose row has a headline**, which is almost every live Claude or Auggie tile. The losses: "⚙ N background agents · M shells" (owner ruling quoted at `claude.py:893-897`), "▶ todo", and on an awaiting tile the blocked job's **question** `needs` (`claude.py:948-950`). The plan's own D1 text never cites the earlier "'awaiting' … leave that state alone" ruling (`ext_cr_board.js:2822-2823`). Real data: 38 of 53 blocked jobs have `detail != needs`, so the headline (detail) is not the question. Existing tests stay green only because their fixtures carry no `headline` key. | A live job row: `headline={label:"Needs input",text:"repo push access insufficient…"}`, `needs:"provide colleague's GitHub username…"` → the tile shows only the detail, and the question is gone (expected: the question still visible). A live row with `bg:3` plus a narration headline → the tile loses "⚙ 3 background agents" (expected: kept). | **Change:** the tile shows the headline first, then keeps today's structural line beneath it. On an awaiting tile that line is `needs` (only when non-empty). On any other tile it is `now_line`, but **the server blanks `now_line` when it is just the narration the headline already shows**, so the same sentence never appears twice. **Must NOT change:** the null-headline fallback (today's exact branches), `list_sessions()`'s own `now_line` (the selfcheck asserts at `test_selfcheck.py:1051,1072` stay as they are), group tiles. `prompt` drops off awaiting tiles only when a headline exists; it stays in the tile tooltip (`:2852`). Put the "leave awaiting alone" ruling to the user as part of D1. | `registry.all_sessions()`, in the §3b block **before** the pops: `lt = s.get("last_text") or ""` · `s["headline"] = list_headline(s, mode)` · `if s["headline"] and s["headline"]["source"] == "narration" and lt and s.get("now_line") == now_phrase(lt): s["now_line"] = ""`. Extend the one-line `from .util import …` (`registry.py:12`) with `now_phrase`. `tileLine(s, state)` returns an array: `var hl = headlineEl(s.headline,'cr-tile-line cr-tile-line--hl'); if (!hl) return [<today's single element or null>]; var sub = state === 'awaiting' ? (s.needs ? h('div',{class:'cr-tile-line cr-tile-line--now'},['⧖ ' + s.needs]) : null) : (s.now_line ? h('div',{class:'cr-tile-line cr-tile-line--now'},[s.now_line.trim()]) : null); return [hl, sub];`. In `sessionTile` (`:2888-2889`), `body.push` each non-null element. The hero tile uses the same path. Auggie is covered by the same seam (its `now_line` comes from `now_phrase(e["last_text"])`, `auggie.py:369`). | Python (`test_list_headline.py`): a **live** non-job Claude row with narration has `all_sessions()` `now_line == ""` while `list_sessions()` `now_line != ""`. A live row with an in-transcript bg agent keeps `now_line` starting `"⚙"`. The same two checks for Auggie (narration blanked, `▶ todo` kept). Node UI: a row with headline plus `now_line:"⚙ 2 background agents"` shows both `cr-tile-line--hl` and `cr-tile-line--now` with that text. An awaiting row with headline plus `needs:"login required"` shows both lines. Red against the plan as written (the tile returns only `hl`). |
| F2 | Med | `md()` linkifies bare URLs (`app.js:157-161`), and job details and narration are full of PR URLs. §4 and §5 handle this only with `pointer-events:none`, which does not take an `<a>` out of the **tab order**. The rail row is a keyboard target (`tabindex=0`, `onkeydown` Enter → `openSession`, `ext_cr_board.js:2124-2125`). Enter on the focused inner link opens the URL in a new tab **and** bubbles to the row's handler. Every row with a URL also gains extra tab stops in the rail, in classic `.sitem`, and on tiles. | headline text `"opened https://github.com/o/r/pull/7"` → the `cr-rail-hl` innerHTML contains `<a href=…>`. Tab reaches it, and Enter both navigates and opens the session (expected: no inner focusable element). | **Change:** row and tile lines render `md()` with anchors unwrapped. The link text stays visible, there is no `<a>`, and the full text stays in `title`. **Must NOT change:** the detail and classic headers (they keep real links), and `md()` itself. | One shared unwrap step at the row level: `md(t).replace(/<a [^>]*>([\s\S]*?)<\/a>/g, "$1")`, applied in `headlineEl` (CR) and in the row use of `hlHtml` (classic: give it an `inline` flag, or unwrap at the `sessionRow` call site). Then **delete** the three `a { pointer-events:none }` rules from §4 and §5, which makes the diff shorter. | Node UI: a headline with a bare URL → the `cr-rail-hl` innerHTML and the classic `shline` markup contain no `<a `, but do contain the URL text. Red against the plan as written. |
| F3 | Med | §7 `test_non_job_row_narration_flattened_and_clipped` **cannot pass as specified**. `_tail_scan` already cuts narration to `t[:200]` (`claude.py:197`), and Auggie does the same (`auggie.py:151`), so `list_headline`'s clip and its `…` never fire on narration. Real data: 206 Claude `last_text`s are exactly 200 chars. The clip only fires on job text (`detail`/`needs`/`result`, ≤400, `claude.py:768`). An implementer will "fix" the red test by weakening the clip. | `"line one\nline two " + "x"*400` → the `text` length is 200 with **no** trailing `…` (the test expects `…`). | **Change:** the test, not the code. Assert the clip through a job row; for narration assert only that it is flattened and ≤200. **Must NOT change:** `LIST_HL_MAX` and `list_headline`. | Split the test into two. (a) Narration: no `"\n"`, `len <= 200`, `source=="narration"`. (b) `test_job_detail_clipped`: a job with `detail = "word " * 100` → `len(text) == 200`, `text.endswith("…")`. | (b) goes red if the clip line in `list_headline` is reverted. (a) guards the flatten step (red if the `" ".join(split())` is removed). |
| F4 | Low | §7 CSS test only checks `max-width:600px/900px` blocks, but the board's breakpoints are 480, 600, 1023 and 1279 (`ext_cr_board.css:475,515,1248,1283,1442,1464,1467,1483,1805,1965`). A `display:none` added in the 1023 block would pass. | A rule `@media (max-width:1023px){.cr-rail-hl{display:none}}` → the test passes (expected: red). | **Change:** check every `@media` block in `ext_cr_board.css` and `app.css`. | Iterate over every `@media[^{]*\{…\}` body and `assertNotRegex(body, r"(cr-rail-hl\|shline\|cr-tile-line--hl)[^{]*\{[^}]*display:\s*none")`. | Red when a hiding rule is planted in the 1023 block. |
| F5 | Low | The pill markup gets hand-written a third time. The plan adds `headlineEl` (board) and `hlHtml` (classic), while `paintGoalLine` (`ext_cr_detail.js:1250-1251`) keeps its own copy of the CR pill. A later change to the band classes can then drift between the CR board and the CR detail. | n/a (a maintenance finding) | **Optional.** Either leave as is (the "no change" direction: the plan already dedupes classic, and the CR detail copy is 2 lines), or have `paintGoalLine` call the board's helper. **Must NOT** touch the detail's markup output. | If taken: export `headlineHtml(hl)` from `CR.board` (the same pattern as `modelShort`/`toolLabel`, `:3225-3250`; the board loads before the detail). `headlineEl` and `paintGoalLine` both call it. | The existing detail headline test stays green (same markup). |
| F6 | Low | Citation errors in §0. "5 s poll, `ext_cr_dialogs.js:1321-1324`" is the **Config dialog help text**; the real list poll is `app.js:1449` (`setInterval(loadSide,5000)`). The roster read measures 1.2 ms, not ~7 ms. | n/a | Correct the §0 facts. No code change. | Edit the text only. | n/a |

### Clean plan (deltas vs the original §1–§9; everything not listed stands as written)

1. **§3b (seam)**, adopting F1. Read `lt = s.get("last_text") or ""` first, then compute `s["headline"]`, then blank `s["now_line"]` when the headline is narration-sourced and `now_line == now_phrase(lt)`, and only then pop `job` and `last_text`. Add `now_phrase` to the existing one-line `.util` import in `registry.py`.
2. **§5 Tile (R1)**, adopting F1. `tileLine` returns `[headlineLine, subLine]`. `subLine` is `needs` on awaiting tiles and the (de-duplicated) `now_line` elsewhere, and either can be null. With a null headline, today's exact branches run unchanged. `sessionTile` pushes each non-null element. **D1 is reworded for the user:** the headline goes on every card, the structural "now" line stays under it, and an awaiting card drops the first `prompt` (tooltip only) when it has a headline. This supersedes the earlier "leave awaiting alone" ruling (`ext_cr_board.js:2822`), so it needs their OK.
3. **§4 and §5 links**, adopting F2. Row and tile lines unwrap `<a>` from `md()` output. The three `pointer-events:none` rules are dropped.
4. **§7 tests:**
   - Replace `test_non_job_row_narration_flattened_and_clipped` with the two tests from F3.
   - Add the F1 tests (Python: Claude and Auggie, a live narration row's `now_line` blanked on the wire, structural `now_line` kept; Node: tile shows headline + `⚙` line, awaiting tile shows headline + `needs`).
   - Add the F2 no-`<a>` assertion.
   - Widen the CSS test to every `@media` block (F4).
   - Red proof adds one step: revert the seam dedupe line and the Python dedupe test goes red; revert the tile's `subLine` and the Node tile test goes red.
5. **§0 facts** corrected per F6. **§9 D2** is unchanged and recommended as written: the contract asks for the 2nd line on every row, so the narration fallback is not live-gated.
6. F5 is optional; the default is no change.
7. **Not examined by this review.** The Node DOM stub was not executed. F2's Enter double-fire is inferred from `ext_cr_board.js:2124-2125` plus standard event bubbling, not observed in a browser. Rendering the pill inside the 2-line `-webkit-box` clamp was not checked in a real browser (step 4's 390/768/1280 px pass covers it).

## Reconciled plan + verdict table

### Orchestrator verdicts on the review (2026-11-13)

| F | Verdict | Decision |
|---|---|---|
| F1 High | confirmed | Accept: tile shows the headline, then KEEPS the waiting question (`needs`) or `now_line` beneath it; server blanks `now_line` when it merely repeats the headline's narration (in `registry.all_sessions`, before raw keys are dropped). Resolves D1 losslessly and respects the prior "leave waiting cards alone" ruling (`ext_cr_board.js:2822`). |
| F2 Med | confirmed | Accept: strip `<a>` from rail/tile headline lines; drop the three pointer-events CSS rules. |
| F3 Med | confirmed | Accept: clip test goes through a job row; narration test asserts flattening only. |
| F4 Low | confirmed | Accept: CSS/layout tests cover the board's real breakpoints (480/1023/1279) as well as rail 600/900. |
| F5 Low | overengineered fix | Cut: optional pill-markup dedupe across classic/CR is a refactor outside the ask. |
| F6 Low | confirmed | Accept: wording — cite the real poll (`app.js:1449`), roster read ≈1.2 ms. |

D2 (narration on idle rows) stays as planned — the ask is a 2nd line on every row.

### Reconciled plan
The reconciled plan is the revised ## Plan above (revision 2, 2026-11-13); deltas: F1 — tile = headline + kept structural line beneath (`⧖ needs` on awaiting unless `headline.covers_needs`, else `now_line`); seam blanks a `now_line` equal to `now_phrase(last_text)` when the headline is narration (§3a/§3b/§5); F2 — rail/tile/classic-row lines unwrap `md()` anchors, the three pointer-events rules are gone, headers keep links (§4/§5); F3 — clip test moved to a job row, narration test asserts flattening only (§7); F4 — CSS test scans every @media block (§7); F6 — §0 cites `app.js:1449` for the 5 s poll and ~1.2 ms roster read; F5 — cut (no pill-markup refactor); planner addition — `covers_needs` (15/53 real blocked jobs would otherwise show the question twice; blanking `needs` server-side is ruled out by `test_selfcheck.py:995-1005`).


## Final adversarial review (opus) on 2900707 — findings to fix (all confirmed by orchestrator)

### Client half (verdict: holds; all 4 skipped red-proofs confirmed red)
- **CF1 Low** — anchor-strip regex `/<a [^>]*>([\s\S]*?)<\/a>/` in `hlHtml` (app.js ~:2315) and `headlineEl` (ext_cr_board.js ~:2851) stops at a `>` that md() generated inside the href (from em/strong/code), leaving garbled attribute text. Repro: `Updated *.py files, see [log](https://ci/job/*/123) ok` → `…/123" target=_blank rel=noopener>log ok`. FIX: use `/<a href="[^"]*"[^>]*>([\s\S]*?)<\/a>/g` in BOTH places; do not touch md() or the header path. TEST: add that input to test_narration_safe_no_anchor_url_text_kept and test_row_url_not_linked_header_url_linked; assert no `target=_blank` and contains `log ok` (red today).
- **CF2 Low** — `.cr-tile-line { flex:1 }` (ext_cr_board.css ~:1686) applies to both `--hl` and `--now`, splitting stretch space between them on short tiles. FIX: add `.tracker-next .cr-tile-line--hl + .cr-tile-line--now { flex: 0 0 auto; }`; null-headline tile untouched. TEST: LayoutTests regex asserts the rule.

### Server half (verdict: holds on real data; one code defect, three test gaps)
- **SF1 Low-Med** — `job_index` (claude.py ~:841) catches only (OSError, ValueError); a deep-nested state.json raises RecursionError, escaping list_sessions → registry swallows it → ALL Claude rows vanish. FIX: `except Exception: continue` there, and `except Exception: return None` in job_for.read() (~:802); precedence/cache unchanged; _blocked_jobs untouched. TEST: deep-nested state.json in a second job dir → job_index doesn't raise and row(SID) keeps its headline (red before).
- **SF2 Med (test only)** — dropping `source == "narration"` from registry.py ~:123 stays green. TEST: live mid-turn transcript + working job detail="Running the gate", HEADER_LINE=summary → now_line == the narration, headline source == "job".
- **SF3 Low (test only)** — precedence mutation (`if sid not in hits:`) stays green. TEST: add job short="0000aaaa" resumeSessionId=SID detail="early" beside the direct job → idx[SID] == job_for(SID), detail == "direct".
- **SF4 Low (test only)** — dropping `source=="job"` from overview.py ~:37 stays green. TEST: HEADER_LINE=narration, narration containing NEEDS, blocked job → covers_needs is False. (M8 clip-boundary: documented only.)

### Fix status (final review)
- CF1: fixed — test_narration_safe_no_anchor_url_text_kept + test_row_url_not_linked_header_url_linked (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
- CF2: fixed — HeadlineCssTests.test_now_line_after_hl_does_not_flex (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
- SF1: fixed — FinalReviewTests.test_deep_nested_state_json_does_not_hide_rows (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
- SF2: fixed — FinalReviewTests.test_narration_source_blanks_now_line_but_job_does_not (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
- SF3: fixed — FinalReviewTests.test_direct_dir_beats_resume_match (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
- SF4: fixed — FinalReviewTests.test_covers_needs_false_for_narration_headline (red before, green after; SF2-SF4 red proven by temporary mutation, restored)
