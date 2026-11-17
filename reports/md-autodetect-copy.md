# Markdown auto-detect + copy on every blockquote (ai-tracker)

Base: `02594b9` (worktree `md-autodetect-copy`, branch `worktree-md-autodetect-copy`).

## Contract (user ask, verbatim)

> "copy paste button for this, also is there any way where the app can intelligently scans whats there in the content which is going to be displayed and selects the markdown renderer and copy paste button on all of these ?"

"this" = the Narration modal's blockquote under **"Prompt to paste into a fresh session:"** (no Copy button: the label has no word "draft"). Behind it, the Control Room timeline shows the same message with literal `- ` markers (inline-only render).

| Clause | Discharged by |
|---|---|
| C1 copy button on "this" quote | Step 2 (every blockquote gets the button) |
| C2 scan the content and pick the renderer | Step 1 (`looksLikeBlockMd`) + Step 3 (gate) |
| C3 "on all of these" | One seam: `mdBlock` (every block surface) + `mdHtml` gate (every CR prose surface) |

## Plan

### Ground truth (read at 02594b9)

- `aitracker/web/app.js`
  - `md(s,safe)` :143 inline only. `mdSafe` :168.
  - `draftLabel` :172, `draftLabelBefore` :176 — label above a quote whose text says "draft".
  - `hasDraftQuote(s)` :181-198 (+ `window.hasDraftQuote` :199) — fence-aware scan, used ONLY by the CR gate.
  - `mdBlock(s)` :201-258. Quote branch :238-251: button only `isDraft`; a draft also joins `>` runs split by blank lines.
  - `copyCode(btn)` :2559 already prefers `.cpsrc` textarea (clean `> `-stripped source). No change needed.
  - Every `mdBlock` consumer inherits Step 2 for free: `openText` :2300 (the Narration modal in the screenshot), `renderMdView` :2249 (.md file preview), `ext_cr_dialogs.js` :2301/:2311, and `mdHtml` when it routes to block.
  - Classic narration row :2091 is a one-line clamped `.narr` row whose click opens `openText` (block). Leave it inline.
- `aitracker/web/ext_cr_detail.js`
  - `mdHtml(ctx,text)` :197; gate :220 = fence OR `hasDraftQuote`. Callers: prompt :3266, narration :3300 and diagram prefix/suffix :3281-3282, ask :3308/:3316, summary :2861-2865, notes :2878, decisions :2778-2782, phone awaiting :1178/:1185. All inherit the new gate; no call site changes.
  - `mdHtmlSafe` :241 (agent task label, machine text): fence-only gate. **Unchanged.**
  - Delegated click listener :1798-1800: `ev.target.closest("[data-act]")`. Every timeline entry carries `data-act="timeline-entry-open"` (:3260). So a `.codecopy` click inside an entry runs `copyCode` AND bubbles up to open the entry modal. This bug already exists for fences. It will show up far more often once quotes and auto-detected messages carry buttons.
  - Phone presence `narrEl.textContent = pres.now` :1149 is a one-line live strip, the same reason `paintGoalLine` :1248 refuses block. **Leave it.**
- CSS: `.cr .cblock`, `.cr .codecopy`, `.cr .mdq`, `.cr .cblock.dq .mdq{padding-right:72px}` (ext_cr_detail.css :1521-1544) and the `.msgbody` twins (app.css :396-408) already exist. `.crd-narration-text` is `white-space:pre-wrap` (:1474). That is harmless because `mdBlock` joins its output with `""`. **No CSS change.**

### Step 1: detector in `aitracker/web/app.js` (replaces `hasDraftQuote`, same spot :179-199)

Delete `hasDraftQuote` and `window.hasDraftQuote`. The new predicate covers them: a draft needs a `>` line, and any `>` line is decisive. They have no other production caller (grep: only ext_cr_detail.js:220). Keep `draftLabel`/`draftLabelBefore`, which `mdBlock` still uses.

```js
// Does this text need the block renderer? (ext_cr_detail.js's mdHtml routes to mdBlock when true.)
// Counts only markers mdBlock itself renders. A fence, a heading, a blockquote or a table is decisive.
// List items need >= 2 lines, so prose like "- that's it" or "1. first" stays inline.
function looksLikeBlockMd(s){
  s=(s||"").replace(/\r/g,"");
  if(s.indexOf("```")!==-1) return true;
  const L=s.split("\n"); let items=0;
  for(let i=0;i<L.length;i++){
    const l=L[i];
    if(/^#{1,6}\s+\S/.test(l)||/^\s*>/.test(l)) return true;
    if(l.includes("|")&&i+1<L.length&&/^[\s|:-]+$/.test(L[i+1])&&L[i+1].includes("-")&&L[i+1].includes("|")) return true;
    if(/^\s*(?:[-*+]|\d+\.)\s+/.test(l)&&++items>=2) return true;
  }
  return false;
}
window.looksLikeBlockMd=looksLikeBlockMd;
```

The regexes are copied from `mdBlock`'s own branches (heading :226, table `sep` :203, lists :233/:236, quote :238). No fence tracking is needed, because any fence already means block.

### Step 2: copy button on every blockquote in `mdBlock` (app.js :248-251)

Replace the `isDraft ? … : …` push with one shape:

```js
      // every quote gets the code-block copy button (its source, `> ` stripped, in .cpsrc). A "draft" label
      // only sets the title and lets blank-line-split `>` runs join into one quote (above)
      out.push(`<div class="cblock dq"><button class=codecopy onclick="copyCode(this)" title="${isDraft?"Copy this draft":"Copy this quote"}">${ico('copy')} Copy</button><textarea class=cpsrc hidden readonly>${esc(raw)}</textarea><blockquote class=mdq>${inner}</blockquote></div>`); continue; }
```

- Draft multi-paragraph joining (:241-244) is unchanged. Plain split quotes stay two quotes with two buttons.
- Nested quotes: the inner `mdBlock(raw)` recursion gives the inner quote its own button. `copyCode` uses `btn.parentNode.querySelector(".cpsrc")`, and each cblock's own textarea comes first, so each button copies its own source. Accepted as rare. Fallback if it looks noisy: add a second parameter `mdBlock(s, inQuote)` and skip the button when `inQuote`.
- XSS: `raw` goes through `esc()` exactly as today's draft branch does. `inner` comes from `mdBlock` (escape-first).

### Step 3: gate in `aitracker/web/ext_cr_detail.js`

- :220 becomes `if (text && typeof looksLikeBlockMd === "function" && looksLikeBlockMd(text)) {`. The fence check moves inside the predicate. Shorten the :198-219 comment's last sentence to "Text the detector flags (fence, heading, quote, table, 2+ list items) goes to mdBlock; everything else keeps the inline path."
- `mdHtmlSafe` :241: no change (machine task labels stay fence-only).
- Click guard at :1799, first line of the listener body:
  ```js
      if (ev.target.closest(".codecopy")) return;   // Copy inside a timeline entry copies; it must not also open the entry
  ```
  (`copyCode` runs from the inline `onclick` before bubbling, so returning here only stops the entry-open.)

### Step 4: tests (no new file; edit what is there)

`tests/test_draft_copy.py`, the main home (runs the real app.js under node):
- DRIVER adds:
  - `OUT["paste_prompt"] = mdBlock("**Prompt to paste into a fresh session:**\n\n> Continue the X work.\n> - step one\n> - step two")`
  - `OUT["looks"] = [looksLikeBlockMd(c) for c in CASES]`. Positives: the paste-prompt text, `"## h"`, `"- a\n- b"`, `"1. a\n2. b"`, `"a | b\n|---|---|"`, `"x\n```\ny\n```"`, `"> one line"`. Negatives: `"plain prose"`, `"done - that's it"`, `"- just one"`, `"#1 priority"`, `"a | b no sep"`, `""`, `null`.
  - Routing under node: `_extract_function(<ext_cr_detail.js text>, "mdHtml")` (import from `tests.test_cr_detail_agents_pill_and_markdown`) appended after app.js, with the same `ctx.markdown` stub that file uses. `OUT["route_list"] = mdHtml(ctx, "Done:\n- one\n- two")`, `OUT["route_paste"] = mdHtml(ctx, <paste text>)`, `OUT["route_single"] = mdHtml(ctx, "- that's it")`.
- New asserts:
  - `paste_prompt`: exactly 1 `class="cblock dq"`, `title="Copy this quote"`, cpsrc `"Continue the X work.\n- step one\n- step two"`, no `&gt;`.
  - The `looks` list equals the expected booleans.
  - `route_list` contains `<ul class=mdul>`.
  - `route_paste` contains `cblock dq`.
  - `route_single` has no `<ul` and no `<p class=mdp>` (the inline path kept).
- Update to the new agreed behaviour (an expected consequence of C1/C3):
  - `test_negatives_no_button`: `neg_prose` now has 1 `cblock dq`. Keep `neg_list`/`neg_mermaid` at 0.
  - `test_plain_blockquote_…`: becomes `(1 mdq, 1 codecopy, 0 &gt;)`, plus cpsrc `"just a quote\ntwo lines"`. Rename it to `…_gets_copy_button`.
  - `nested_md`: `cblock dq` count 2.
  - `plain_split_quotes`: 2 mdq, 2 `cblock dq` (still not merged).
  - Delete `test_has_draft_quote_predicate`, `test_has_draft_quote_agrees_with_mdblock_for_nested` and the `OUT["has"]` line.
  - `WiringTests`: assert `'typeof looksLikeBlockMd === "function" && looksLikeBlockMd(text)'` and `"function looksLikeBlockMd"` are in `build_page()`, with no `location.hostname` in the 400 chars after it. Add one order check: in ext_cr_detail.js, the text after `node.addEventListener("click", function (ev) {` has `closest(".codecopy")` before `closest("[data-act]")`.
- `tests/test_md_fence_xss.py`: remove `OUT.draft_open/draft_real/draft_after_fence` (:35-37) and `test_draft_quote_scan_agrees_on_fence_length` (:85-90). Fence-length awareness was only needed by `hasDraftQuote`, and any fence now means block.
- `tests/test_job_headline.py` :222/:224: needle `hasDraftQuote` becomes `looksLikeBlockMd`.

Red proofs (each one reverted, watched fail, restored with a scoped Edit, never `git stash`):
1. Restore the old :220 gate: `route_list` fails.
2. Restore the `isDraft ?` ternary: `paste_prompt` and the plain-quote tests fail.
3. Drop the click-guard line: the order check fails.
4. Change the list threshold to `>=1`: `"- just one"` fails in `looks`.

Gate: `unset TRACKER_AUTH; make check` prints `selfcheck ok`. If you see OOM `Killed: 9`, run per module: `python -m unittest tests.test_draft_copy tests.test_md_fence_xss tests.test_job_headline tests.test_cr_detail_agents_pill_and_markdown tests.test_classic_markdown_and_links`, then the full gate. Commits run the full hook gate, so use a Bash timeout of 600s or more.

### Sequencing

1. Steps 1+2 (app.js) together. 2. Step 3 (ext_cr_detail.js depends on the global from step 1; the `typeof` guard keeps it safe in either order). 3. Step 4 tests, then the red proofs. 4. `make serve` restart. **This is a UI change: the page is baked at startup.** Eyeball: a CR narration with a list renders as `<ul>`, the paste-prompt quote has Copy, and clicking Copy in the timeline does not open the modal. 5. `/branch-sync`, re-gate, push `personal <branch>`.

### Risky spot + fallback

**False positives in `looksLikeBlockMd`.** When prose trips it, the only visible change is that `mdBlock` joins soft line breaks inside a paragraph with spaces (the inline path keeps them under `pre-wrap`). A stray leading `>` (a quoted shell prompt) also renders as a quote with a Copy button. No content is lost, and there is no new XSS surface, because `mdBlock` is escape-first and is already what the modal shows for the same text. Fallback: all the tuning sits in one function, so either raise the threshold (make `>` need 2 lines too, or demand list items be consecutive) or drop a marker class. No call site changes.

Secondary: a single-item list (`"- one"`) stays inline by design. Ask/decision option pills (`<span class=crd-ask-pill>`) could in theory receive block HTML if one option is itself multi-line markdown. That is accepted as practically never seen, with no change.

### Decisions the user may want to overrule

1. **Copy on EVERY blockquote**, not only label-led ones (the brief's direction). The alternative is to widen `draftLabel` to any bold or heading lead line ending in `:`. That would cover "Prompt to paste…" but leave bare quotes without a button.
2. **Detector thresholds.** One `>`/`#`/table/fence line flips to block, but lists need 2 or more items. Phone presence and the classic narration row stay one-line inline (both are clamps; their click-through modal already uses `mdBlock`). The bundled click-guard fixes a pre-existing fence bug: Copy also opened the entry. It can be dropped if out of scope.

## Review

Adversarial review (opus) of the plan above, against the code at `02594b9`. No source edits. Method: (a) the plan's Steps 1–3 applied **in memory** and run under node on synthetic and real inputs (`~/.claude/jobs/c57b10c7/tmp/probe_review.py`); (b) the plan plus the fixes below applied to a **scratch copy** of the worktree (`…/tmp/wtcopy`, `…/tmp/patch_copy.py`), where `tests.test_mermaid`, `test_classic_markdown_and_links`, `test_cr_dialogs_markdownfork_and_scrim`, `test_cr_agent_map_entry`, `test_cr_detail_agents_pill_and_markdown`, `test_cr_timeline` and `test_integration.TestNarrationBareUrlsAreLinks` stay green. The only reds are the ones the plan already lists: `test_draft_copy` and `test_md_fence_xss` drivers still call `hasDraftQuote`, plus the old wiring needle. (c) Read-only scans of the last ~270 transcripts (`…/tmp/scan_*.py`) to size each risk.

**What holds (checked, no finding):**
- **Routing of the real message.** I pulled the actual "Prompt to paste into a fresh session:" message from `~/.claude/projects/-…-dw-vida-stack/82ce95d1-….jsonl`. Its shape is a bold label, one `> ` line, a `**The draft script**` paragraph, `- **Usage:**` bullets, and 2-space sub-bullets. With the plan applied, CR `mdHtml` and the modal's `mdBlock` both emit `cblock dq` with a Copy button. The cpsrc is the full prompt with `> ` stripped, and the bullets become `<ul>`.
- **XSS.** I quoted `</textarea><script>…` inside a quote. It is escaped as `&lt;/textarea&gt;…` both in cpsrc and in the paragraph. A `[x](javascript:…)` link stays text. The `title` is a constant.
- **Copy source.** Multi-paragraph quotes joined by a `>` line keep their `\n\n`. Nested quotes strip exactly one level, so the outer copy keeps `> inner`, which is correct. `copyCode`'s `btn.parentNode.querySelector(".cpsrc")` is scoped to each button's own cblock, so a fence nested in a quote copies its `<code>`.
- **Blank-split quotes.** The worry: two `>` runs separated by a bare blank line under a non-draft label would give two buttons, each copying half a prompt. Scan result: 95 quote runs, **0** split this way. No join-rule widening is needed.
- **Callers.** `hasDraftQuote` appears only at ext_cr_detail.js:220, tests/test_draft_copy.py:3,25-27,156-158, test_md_fence_xss.py:35-37 and test_job_headline.py:222,224. The plan covers all of them. No `.map(mdBlock)` or other second-argument caller exists, so adding an `mdBlock` parameter is safe.
- **Click guard.** The bug is real. Every timeline entry carries `data-act="timeline-entry-open"` (ext_cr_detail.js:3260). The single delegated listener (:1798-1800) does `closest("[data-act]")` and opens the entry (:1974). So a Copy click copies AND opens the modal. The one-line early return is the minimal right fix:
  - `closest` works when the target is the SVG `<use>` inside the button.
  - Enter or Space on the button also dispatches `click`.
  - `stopPropagation` inside mdBlock's onclick strings would be wider (three emit sites) for no gain.
- **Threshold.** In recent narration the detector flips 3693 of 12205 texts and 47 of 1336 user prompts. The flipped texts are lists, quotes, headings and tables, so the plan's thresholds are sound.

| # | Sev | Finding |
|---|---|---|
| R1 | Medium | Ordered lists renumber from 1 after a sub-bullet or blank line. The CR panel gets this newly; the inline path showed the right number |
| R2 | Medium | Hard line breaks inside a paragraph collapse to spaces, which wrecks pasted logs in the CR prompt bubble |
| R3 | Medium | Missed surface: the classic Agent modal (also opened from the CR agents panel) still renders an agent's report inline-only, with raw `- `/`> ` and no Copy |
| R4 | Low | Nested quotes stack a Copy button per level and compound the 72px right padding |
| R5 | Low | The README capability row "Draft-reply copy button in narration" goes stale |
| R6 | Low | The click-guard test is source-order only. A sibling gap: a link click inside an entry also opens the modal |
| R7 | Low | A lazy-continuation line (no `>`) falls out of the quote and is not copied |
| R8 | Low | Accepted false positives: `# of …` becomes a heading, `+ a`/`+ b` become bullets, npm's `> pkg@1 build` echo becomes a quote |
| R9 | Low | The whole-message Copy (`copyModal`) now picks up a "Copy" label per quote |
| R10 | Low | Auto-routed CR entries gain the last block's 9px bottom margin |

### R1 (Medium): ordered lists renumber after sub-bullets or blank lines

- **Defect.** In app.js:233-235 (`mdBlock` ol branch), `"<ol class=mdul>"` never carries `start`. Any non-item line ends the `<ol>`, and the next item opens a fresh `<ol>` numbered from 1.
- **Repro.** The input `1. **First**\n   - sub a\n2. **Second**\n3. Third` renders as `<ol>…First</ol><ul>…</ul><ol><li>Second</li><li>Third</li></ol>`, so the reader sees "1. First · sub a · 1. Second 2. Third". Expected: "2. Second 3. Third". The same happens with `1. one\n\n2. two`.
- **Frequency.** 83 of 3693 flipped narration texts (2.2%) and 8 of 47 flipped prompts. Claude's usual list style, `N. **X**` plus indented `- detail`, triggers it.
- **Why it matters now.** The modal already does this. The plan is what newly exposes it in the CR timeline, summary and notes, where the inline path used to show the literal correct "2.".
- **Direction.** Keep the source's first number. Do NOT change how items are collected and do NOT try to nest sub-lists; flattening is accepted.
- **Way.** In the `if(/^\s*\d+\.\s+/.test(l)){ const it=[];` branch, declare `const it=[], n=parseInt(l,10)||1;`. Emit `"<ol class=mdul"+(n>1?" start="+n:"")+">"+…`. `parseInt` skips leading whitespace and `n` is a number, so no injection is possible. Verified in the scratch copy: `<ol class=mdul start=2>`, and every other markdown suite stays green.
- **Test (red before).** In test_draft_copy DRIVER:
  - Add `OUT["ol_restart"]=mdBlock("1. a\n   - x\n2. b")` and assert `'<ol class=mdul start=2>'` is in it.
  - Add `OUT["ol_plain"]=mdBlock("1. a\n2. b")` and assert `start=` is not in it.

### R2 (Medium): soft line breaks collapse inside paragraphs

- **Defect.** app.js:256 (`mdBlock` paragraph) builds `md(p.join(" "))`. The CR inline path keeps `\n` under `.crd-narration-text{white-space:pre-wrap}` (ext_cr_detail.css:1470-1477). Once the detector flips a text, its adjacent lines merge.
- **Repro.** `**Status:** green\n**Next:** push\n- a\n- b` currently shows two lines in the CR panel. Under the plan it shows `Status: green Next: push` on one line. A prompt with pasted unfenced shell or log output that has a `# comment` or two `- ` lines collapses the whole log into one wrapped paragraph.
- **Frequency.** 51 of 3693 flipped narration texts (1.4%), but **12 of 47** flipped user prompts (25%).
- **Plan's position.** The plan names this as "the only visible change" and accepts it. For the prompt bubble, that acceptance is understated.
- **Direction.** Keep each source line break as `<br>` inside the paragraph. Do NOT split `md()` per line, which would break a `**bold**` or `` `code` `` that spans lines. Do NOT touch list, table or quote assembly.
- **Way.** Make that one line `out.push(`<p class=mdp>${md(p.join("\n")).replace(/\n/g,"<br>")}</p>`);`.
  - XSS: `md` escapes first, and its href and bare-URL patterns exclude whitespace, so a `\n` (and therefore a `<br>`) can never land inside an attribute.
  - Siblings: this also changes the classic modal (`openText`, `renderMdView`) and `ext_cr_dialogs.js` :2301/:2311, all toward how Claude Code's terminal shows the message.
  - Verified in the scratch copy: test_mermaid's `<p class=mdp>intro</p>`, the classic table/link tests, the dialogs and integration tests all stay green.
- **Test (red before).**
  - Assert `mdBlock("a\nb")` equals `"<p class=mdp>a<br>b</p>"`.
  - Assert `mdBlock("**x\ny**")` contains `<strong>x<br>y</strong>`.
  - **Decision for the user.** This is the one fix that visibly changes the classic modal. The alternative is to accept the collapse (the plan as written).

### R3 (Medium): the Agent modal still shows raw markdown

- **Defect.** app.js:2519 (`openAgent`) renders a background agent's narration, the agent's own prose and final report, with `md(d.narration)`. That is inline only: no lists, no quotes, no Copy. The CR agents panel opens this same classic modal (ext_cr_boot.js:517).
- **Repro.** An agent whose report ends with `**Prompt to paste into a fresh session:**\n> …\n- **Usage:** …` shows literal `> ` and `- ` with no Copy button. That is exactly the user's complaint, on the surface they open most for handovers.
- **Direction.** Route through the same detector. Do NOT change the `msgbody` class, because the `.cmdcode` task text relies on pre-wrap, and mdBlock's output has no literal newlines outside `<pre>`/`<textarea>`, so pre-wrap is harmless. Do NOT switch to `mdSafe`: this is prose, the same as narration.
- **Way.** Make that expression `(d.narration?(looksLikeBlockMd(d.narration)?mdBlock(d.narration):md(d.narration)):"<div class=empty>no narration recorded</div>")`. The click guard is not needed here, because the classic modal has no delegated `data-act` listener (app.js:2769 already ignores buttons).
- **Test (red before).** In `WiringTests`, assert `"looksLikeBlockMd(d.narration)?mdBlock(d.narration):md(d.narration)"` is in `build_page()`.

### R4 (Low): nested quotes stack buttons and padding

- **Defect.** Under the plan, the recursive `mdBlock(raw)` at app.js:247 gives every nesting level its own `cblock dq`. ext_cr_detail.css:1543 and app.css:402 add `padding-right:72px` per level.
- **Repro.** An unfenced REPL paste `>>> import foo\n>>> foo.bar()` gets three stacked Copy buttons and loses 216px of width.
- **Direction.** This is the plan's own stated fallback; adopt it now, since it is three tokens. A nested **non-draft** quote stays a bare `<blockquote class=mdq>`. A nested **draft** keeps its button, which is the existing `nested_md` behaviour.
- **Way.** Change the signature to `function mdBlock(s,inQ){`. The recursion becomes `inner=mdBlock(raw,true)`. Change the push to `out.push(inQ&&!isDraft ? `<blockquote class=mdq>${inner}</blockquote>` : `<div class="cblock dq">…</div>`); continue; }`.
- **Test (red before).**
  - Add `OUT["nested_plain"]=mdBlock("> outer\n> > inner")` and assert exactly 1 `cblock dq`.
  - `nested_md` stays at 2.
  - The REPL case gives 1.

### R5 (Low): stale README capability row

- **Defect.** README.md:250 still says "Draft-reply copy button in narration".
- **Direction and way.** Rename the row to "Copy button on every quote; Control Room auto-detects block markdown (lists, quotes, headings, tables, fences)". Keep the three ✅ cells. No test.

### R6 (Low): click-guard test strength, and the link-click sibling

- **Test.** The plan's order check is a source-substring test. That is acceptable, because the listener lives inside `mount`'s closure and cannot be driven without a DOM. Keep it.
- **Sibling gap.** A click on a link `<a>` inside an entry also opens the modal. That is pre-existing (the goal line guards it, the timeline does not). **No change**: it is out of scope. Document it in the commit.

### R7 (Low): lazy-continuation lines are dropped from the copy

- **Repro.** `> Continue the work\nand read the plan first.` copies only the first line. CommonMark would treat the second line as part of the quote.
- **Direction.** No change; this is a known `mdBlock` gap, the same as base. Document it.

### R8 (Low): accepted false positives

- **Cases.** `# of retries is 3` renders as an h2. `+ a\n+ b` render as bullets. npm's `> pkg@1.0 build` echo lines render as a quote with Copy.
- **Direction.** No change. All of these are what the modal already shows. The plan's single-function fallback is the right lever if one of them bites.

### R9 (Low): whole-message Copy picks up "Copy" labels

- **Defect.** `copyModal` (app.js:2534) copies `innerText`, which now includes a " Copy" label for each quote.
- **Direction.** No change; fences already do this. Document it.

### R10 (Low): extra bottom margin on auto-routed entries

- **Defect.** The last `.mdp`/`.mdul`/`.cblock` adds 9px at the bottom of a CR entry that the inline path did not. Fence-bearing entries already do this today.
- **Direction.** No change. If it looks off in the eyeball step, add `.cr .crd-narration-text > :last-child, .cr .crd-bubble-prompt > :last-child { margin-bottom: 0; }` to ext_cr_detail.css.

**Overengineering check.** Nothing in the plan is wider than its defect:
- Deleting `hasDraftQuote` and its fence-length tests is correct, because the code is superseded.
- The detector copies only `mdBlock`'s own markers.
- There is no CSS change and no per-panel fork.

**Not examined.** The ext_cr_dialogs pop-out layout of the new buttons (CSS claims `.cr` scope; I did not render it). Mobile widths of `.crd-bubble-prompt` with a 72px-padded quote. Render cost of `mdBlock` on ~30% of entries per 2s poll: it is linear, and I judged it negligible but did not measure it.

## Clean plan

The design is the same as the plan: one detector, one gate, Copy on every quote, and one click guard. It adds three small `mdBlock` touches (R1, R2, R4), one more call site (R3) and a README row (R5).

1. **app.js: detector** (plan Step 1, unchanged). Replace `hasDraftQuote` and `window.hasDraftQuote` (:181-199) with `looksLikeBlockMd` plus `window.looksLikeBlockMd`. Keep `draftLabel`/`draftLabelBefore`.
2. **app.js: `mdBlock`**:
   - **(a) Copy on every top-level quote** (plan Step 2, adjusted by R4). The signature becomes `mdBlock(s,inQ)` and the recursion becomes `mdBlock(raw,true)`. Push `inQ&&!isDraft ? bare blockquote : <div class="cblock dq">…title="${isDraft?"Copy this draft":"Copy this quote"}"…<textarea class=cpsrc hidden readonly>${esc(raw)}</textarea>…</div>`. Draft blank-line joining is unchanged.
   - **(b) R1.** The ol branch gets `n=parseInt(l,10)||1` and `<ol class=mdul${n>1?" start="+n:""}>`.
   - **(c) R2 (user decision).** The paragraph becomes `md(p.join("\n")).replace(/\n/g,"<br>")`.
3. **app.js: `openAgent` :2519 (R3).** Use `looksLikeBlockMd(d.narration)?mdBlock(d.narration):md(d.narration)`.
4. **ext_cr_detail.js** (plan Step 3, unchanged):
   - The :220 gate becomes `typeof looksLikeBlockMd === "function" && looksLikeBlockMd(text)`, and the comment is shortened.
   - `mdHtmlSafe` is untouched.
   - Add `if (ev.target.closest(".codecopy")) return;` as the first line of the :1798 listener.
5. **README.md:250 (R5).** Rename the capability row.
6. **Tests**: plan Step 4 as written, plus these additions and adjustments:
   - **Additions.** `ol_restart` contains `<ol class=mdul start=2>`. `ol_plain` has no `start=`. `mdBlock("a\nb")==="<p class=mdp>a<br>b</p>"` and the `**x\ny**` bold-span case (drop both if R2 is declined). `nested_plain` has 1 `cblock dq`. The R3 wiring needle goes in `WiringTests`.
   - **Adjustments.** `nested_md` stays at 2 (the plan already says 2). Update the test_draft_copy docstring's `hasDraftQuote` mention.
   - **Red proofs.** The plan's four, plus three more. Each is reverted with a scoped Edit, never `git stash`:
     - Drop `start=`: `ol_restart` goes red.
     - Restore `join(" ")`: the `<br>` assert goes red.
     - Drop the `inQ&&!isDraft` arm: `nested_plain` goes red.
7. **Sequencing and gate** (as the plan):
   1. app.js.
   2. ext_cr_detail.js.
   3. README.
   4. Tests and the red proofs.
   5. Run `unset TRACKER_AUTH; make check` and confirm `selfcheck ok` (per-module if OOM). Use a Bash timeout of at least 600s for the commit.
   6. Run `make serve` to restart; this is a UI change baked at startup. Eyeball the CR narration list as `<ul>`, the paste-prompt quote's Copy, Copy not opening the entry, a `1.`/sub-bullet/`2.` list numbering correctly, and the Agent modal showing block markdown.
   7. `/branch-sync`, re-gate, then push `personal <branch>`.
8. **Document in the commit (no code).** R6's link-click gap, R7's lazy-continuation gap, R9's whole-modal "Copy" label, and R8's accepted false positives.

**Decisions for the user:**
1. R2, `<br>` soft breaks: this also changes the classic modal. Take it, or accept the collapse.
2. Copy on every quote: kept from the plan.
3. R3, extending to the Agent modal: included in this plan. It can be dropped if "all of these" means only the panels in the screenshot.

## Reconciliation (main thread, 2026-11-17)

| # | Finding | Verdict | Action |
|---|---|---|---|
| R1 | `<ol>` renumbers from 1 after a break (app.js:238, no `start`) | confirmed | accept — `<ol start=N>` |
| R2 | paragraph lines joined with spaces (pasted logs flatten) | confirmed; changes the classic modal too | **user decision** |
| R3 | Agent modal `openAgent` (app.js:2519) uses inline `md()`, so agent reports stay raw with no Copy | confirmed (re-read app.js:2519) | accept — route through the detector |
| R4 | nested quotes each get their own Copy plus indent | confirmed, low | accept — outer quote only |
| R5 | README:250 capability row goes stale | confirmed | accept |
| R6–R10 | link click opens entry; lazy continuation; `# of…`/`> pkg` false positives; whole-message Copy picks up "Copy" labels; 9px margin | low | no change — documented known gaps |
| — | missed by both: phone presence line (ext_cr_detail.js:1149) stays raw text | deliberate | leave — one-line strip that opens the block-rendered modal |

Scope after reconcile: the Clean plan above, with R2 gated on the user's answer.

## User decisions (2026-11-17)
- R2: **keep line breaks** — single newlines inside a paragraph render as `<br>` (applies to the classic modal too).
- Sign-off: **go ahead** with Copy on every blockquote (outer quote only, per R4).

## Implementation status
- [x] implement Clean plan + R2 (sonnet)
- [ ] adversarial implementation review (opus)
- [ ] branch-sync, gate, push to personal

## Red proofs
Each fix reverted with a scoped replace (never git stash), the named test run, then restored.
- old fence-only gate in mdHtml -> `DraftCopyTests.test_cr_gate_routes_detected_text_to_mdblock`: `'<ul class=mdul>' not found in 'Done:\n- one\n- two'`
- click guard dropped -> `WiringTests.test_copy_click_does_not_open_the_timeline_entry`: `'closest(".codecopy")' not found`
- list threshold `>=1` -> `test_looks_like_block_md_detector`: `"- just one"` flips to True, lists differ
- `start=` dropped -> `test_ordered_list_keeps_source_number_after_break`: `'<ol class=mdul start=2>' not found`
- `join(" ")` restored -> `test_single_newline_in_paragraph_is_br`: `'<p class=mdp>a b</p>' != '<p class=mdp>a<br>b</p>'`
- `inQ&&!isDraft` arm dropped -> `test_nested_plain_quote_has_one_button`: `2 != 1`
- title ternary reverted -> `test_paste_prompt_quote_gets_copy`: `title="Copy this quote"` not found
- openAgent detector reverted -> `WiringTests.test_cr_mdhtml_routes_draft_text_to_mdblock_and_page_carries_it`: R3 needle not found
- I1 `file?` join reverted -> `test_file_preview_keeps_soft_wrap_join`: `'<p class=mdp>a<br>b</p>' != '<p class=mdp>a b</p>'`
- I1 `mdBlock(content,false,true)` / CR dialogs `false, true)` reverted -> `WiringTests.test_file_previews_pass_file_flag`: needle not found (each separately)
- I2 `_liInd` dropped -> `test_indented_list_items_are_indented`: `<li style="margin-left:1.2em">b</li>` not found in flat `<ul><li>a</li><li>b</li><li>c</li></ul>`
- I3 `esc(raw)`->`raw` -> `test_quote_source_textarea_is_escaped`: `<img` unexpectedly found
- I4 title always "quote" -> `test_draft_label_titles_the_button_draft`: `title="Copy this draft"` not found
- I5 `upgradeMermaidIn` removed from openAgent -> `test_file_previews_pass_file_flag`: needle not found

## Implementation review (opus, adversarial, 2026-11-17)

Reviewed the staged diff (app.js, ext_cr_detail.js, README, three test modules) against the Clean plan and the User decisions. Method: node probes of the real `looksLikeBlockMd`/`mdBlock`/`mdHtml` (the CR `mdHtml` extracted from `build_page()`), including the real "Prompt to paste" message pulled from the dw-vida-stack transcript (`82ce95d1…jsonl`). In-memory mutation runs patched the app.js text the node harnesses read; no file on disk was edited. Probe scripts are in `~/.claude/jobs/c57b10c7/tmp/` (`probe.py`, `probe_tail.py`, `mutate.py`).

**Re-verified independently (holds):**
- The 163 tests in these modules pass: `test_draft_copy`, `test_md_fence_xss`, `test_classic_markdown_and_links`, `test_cr_detail_agents_pill_and_markdown`, `test_cr_dialogs_markdownfork_and_scrim`, `test_cr_agent_map_entry` and `test_mermaid`. So do `test_integration.TestNarrationBareUrlsAreLinks` and `test_job_headline` (17 tests).
- **(1) R2 `<br>`.** `<br>` comes only from the paragraph branch. Fence, mermaid, table, heading and list output never contains one, and nothing puts a `<br>` inside `<pre>`. A double `<br>` cannot occur, because a blank line ends the paragraph. CRLF is stripped first. `md()` never puts a newline inside an attribute, since href and URL patterns exclude `\s`, so the `\n`→`<br>` replace cannot break an attribute. Bold, code and link spans that cross a line keep the span, for example `<strong>x<br>y</strong>`. An italic that crosses a line stays literal, which matches the CR inline path, where `[^*\n]` already applied.
- **(2) XSS.** `> </textarea><img src=x onerror=…>` renders as `&lt;/textarea&gt;…` both in `.cpsrc` (RCDATA, so `.value` decodes to the exact source) and in the rendered quote. The title strings are static.
- **(3) The real message.** It renders as a block in the classic `openMsg`→`openText`→`mdBlock` path and in CR `mdHtml` (the detector returns true). There is one `cblock dq` with `title="Copy this quote"`. `.cpsrc` holds the exact quote source with `> ` stripped, backtick paths intact and no `&gt;`. The `- **Usage:**` bullets become a `<ul>`.
- **(5) Click guard.** It is the first statement of the only delegated click listener, ext_cr_detail.js:1799. No element in ext_cr_*.js carries both `.codecopy` and `data-act`, so the guard cannot swallow another action. The inline `onclick="copyCode(this)"` still fires, because it runs on the button before the event bubbles.
- **(6) `hasDraftQuote`.** Zero references remain in `aitracker/`, `tests/`, `scripts/` or README. `dist/` is generated.

### Findings

| # | Sev | Finding | Verdict |
|---|---|---|---|
| I1 | Medium | R2 `<br>` also hits **file** previews: hard-wrapped `.md` files render ragged | user decision (R2 was asked about messages) |
| I2 | Medium | Indented sub-bullets now flatten in CR. The real message's 3 sub-bullets become siblings of their parent | fix or explicitly accept |
| I3 | Low | No test pins the escaping of the new `.cpsrc` on plain quotes: an `esc(raw)`→`raw` mutant **survives** | fix (test only) |
| I4 | Low | The draft title `Copy this draft` is unpinned: an always-"Copy this quote" mutant **survives** | fix (test only) |
| I5 | Low | `openAgent` (R3) never calls `upgradeMermaidIn`, so agent mermaid stays on the fallback | fix (1 line) |
| I6 | Low | A line starting with `>=` (`>= 2 so fine`) is detected and rendered as a quote with Copy | no change: R8 class, document |
| I7 | Info | The red proofs for the guard and for R3 are static source needles, not behaviour | no change: acceptable without a DOM harness |

#### I1 (Medium): R2 `<br>` changes rendered `.md` file previews, not just messages
- **Defect.** The paragraph join at app.js:254 serves every `mdBlock` caller. That includes `renderMdView` (app.js:2246, the classic .md Rendered view) and the CR diff Rendered mode (ext_cr_dialogs.js:2301). Hard-wrapped markdown files then render each source line as its own visual line.
- **Repro.** Take `mdBlock("# T\n\nThis paragraph is hard-wrapped at eighty columns the way many repo\nmarkdown files are, so it continues")`.
  - Actual: `<p class=mdp>…many repo<br>markdown files are…</p>`.
  - Expected for a file: `…many repo markdown files are…`, the CommonMark soft break.
  - Real instance: `~/.claude/CLAUDE.md` and `~/.claude/rules/*.md` are hard-wrapped at about 100 columns, and sessions edit them.
- **Direction.** Keep `<br>` for message surfaces, per the R2 decision. Restore the soft-wrap join for file renders only. Do NOT change the message callers (`openText`, `openAgent`, CR `mdHtml`, ext_cr_dialogs 'text' mode).
- **Way.**
  - Change the signature to `function mdBlock(s,inQ,file)`.
  - Recursion: `mdBlock(raw,true,file)`.
  - Paragraph: `out.push(`<p class=mdp>${file?md(p.join(" ")):md(p.join("\n")).replace(/\n/g,"<br>")}</p>`)`.
  - Callers: `renderMdView` uses `mdBlock(content,false,true)`, and ext_cr_dialogs.js:2301 uses `mdBlock(…join('\n'),false,true)`.
- **Test.**
  - In test_draft_copy, add `OUT["br_file"]=mdBlock("a\nb",false,true)` and assert `=== "<p class=mdp>a b</p>"`.
  - Add WiringTests needles `mdBlock(content,false,true)` and `false, true)` (or the exact dialogs text) in `build_page()`.
  - Red before the fix: the param is absent, so `a<br>b`.
- **The user's call.** If they want `<br>` in file previews too, there is no code change. Add one line to the PR body.

#### I2 (Medium): sub-bullets flatten in Control Room, a regression versus the old inline view
- **Defect.** CR `mdHtml` now sends 2+-item lists to `mdBlock`. The ul branch at app.js:232 matches `/^\s*[-*+]\s+/` at any indent, so nested items join the parent list at the same level. Before this change, CR rendered such text inline under `white-space:pre-wrap` (ext_cr_detail.css:1473), so the 2-space indent stayed visible. The plan (R1 direction, "flattening is accepted") accepted this, but it was never put to the user, and the motivating message itself contains it.
- **Repro.** Take the real message: `- **What it does, per case:**\n  - It runs the case…\n  - It re-runs…\n  - Genuine route…`.
  - Actual (CR and classic): 8 sibling `<li>`, with the three details at the same level as `What it does`.
  - Expected: a nested `<ul>` inside that `<li>`.
  - Also: `1. a\n   - x\n2. b` gives `<ol>…</ol><ul>…</ul><ol start=2>`, three sibling lists.
- **Direction.** Nest by indentation inside the list branches. Do NOT change top-level list detection or how quotes, tables and fences are handled. The ul/ol type switch at the same indent stays a separate list.
- **Way.**
  - In both list branches, record `b=l.match(/^\s*/)[0].length`.
  - Collect items while the line is a list item at indent ≤ b+1.
  - When a non-blank line (list item or continuation) sits at indent > b, push it, dedented by `b+2` (or by the min indent of the run), into a `sub` array on the last item.
  - Render each item as `<li>${md(text)}${sub.length?mdBlock(sub.join("\n"),inQ):""}</li>`.
  - The same loop also absorbs R7-style indented continuation lines into their item.
  - R1's `start=` stays, for a list that genuinely restarts after prose.
- **Test.** Each assert is red on the current code:
  - `mdBlock("- a\n  - b\n- c")` should equal `"<ul class=mdul><li>a<ul class=mdul><li>b</li></ul></li><li>c</li></ul>"`.
  - `mdBlock("1. a\n   - x\n2. b")` should contain exactly one `<ol` and no `start=`. Update `ol_restart` to a prose break, `"1. a\n\nprose\n\n2. b"`, so R1 stays covered.
- **If declined.** Add one line to the PR body: "nested lists render flat (classic already did; CR newly does)".

#### I3 (Low): `.cpsrc` escaping on every quote is untested
- **Defect.** app.js:248, `<textarea class=cpsrc …>${esc(raw)}</textarea>`, now runs for every quote in every CR prose surface, user prompts included. Nothing in tests/ asserts its escaping.
- **Repro.** Run `mutate.py` with `${esc(raw)}`→`${raw}` over `test_draft_copy`, `test_md_fence_xss` and `test_classic_markdown_and_links`. Result: **MUTANT SURVIVED**. A quote line `> </textarea><img src=x onerror=alert(1)>` would then execute.
- **Direction.** Add a test only. The code is correct today.
- **Way.** In `test_md_fence_xss.py` or `test_draft_copy.py`, add `OUT["xss_quote"]=mdBlock("> </textarea><img src=x onerror=alert(1)>")`. Assert:
  - `&lt;/textarea&gt;&lt;img` is in it.
  - `<img` is not in it.
  - `o.count("</textarea>")==1`.
- **Test.** That case itself. Prove it red with the mutant above.

#### I4 (Low): the draft title is unpinned
- **Defect.** app.js:248 has the ternary `isDraft?"Copy this draft":"Copy this quote"`. A mutant that always uses "Copy this quote" survives `test_draft_copy`. The listed red proof only checks the quote arm.
- **Way.** In `test_bharadwaj_*` (or a new test), add `assertIn('title="Copy this draft"', self.OUT["bharadwaj"])`.
- **Test.** That assert. Red under the mutant.

#### I5 (Low): Agent modal mermaid is never upgraded
- **Defect.** app.js:2516 now routes `d.narration` through `mdBlock`, which emits `.mmd-slot`. Unlike `openText` (app.js:2298) and `renderMdView` (app.js:2248), `openAgent` never calls `upgradeMermaidIn`, so a gantt/mindmap fence in an agent report stays on the labelled fallback forever.
- **Way.** Add `upgradeMermaidIn($("msgbody"));` after the innerHTML assignment in `openAgent`. Do not touch `openShell`.
- **Test.** Add a WiringTests needle: the text after `function openAgent` contains `upgradeMermaidIn($("msgbody"))` before `function closeMsg`. It is red now.

#### I6 (Low): `>=` at line start is treated as a quote
- **Repro.** `looksLikeBlockMd("count is 3\n>= 2 so fine")` is true. The quote renders `= 2 so fine` with a Copy button. `mdBlock` has the same quote rule, so it is the same R8 class.
- **Direction.** No change. Document it with R8 in the commit or PR body. If it bites, tighten both regexes to `/^\s*>(?!=)/` together, at the detector, the mdBlock quote branch and the paragraph stop.

#### I7 (Info): red-proof quality
- Every listed red proof does target the behaviour it names. I re-ran the `start=` mutant and it is KILLED.
- Two of the eight are static source needles: the click guard and the R3 `openAgent` routing. With no DOM click harness or async `sessJSON` stub, that is acceptable. No change.

**Verdict:** fix-first, but light. Before commit:
- I3, I4 and I5 are test-only or one-line changes.
- I1 and I2 each need a one-line user call. Either apply the designed fix or record it in the PR body as accepted.

Nothing found is a security or correctness break in the code as staged.

## Implementation review — reconciliation (main thread)
| # | Verdict | Action |
|---|---|---|
| I1 | confirmed — R2 decision covered narration/prompts, not file previews | fix: `.md` file previews (renderMdView, ext_cr_dialogs.js:2301) keep space-joining |
| I2 | confirmed; same flatness the classic modal already had | fix cheap: indent `<li>` by leading-space count (no nested-list parser) |
| I3 | confirmed | add test: `</textarea>` / `<script>` in a quote stays escaped in .cpsrc |
| I4 | confirmed | add test: draft-labelled quote titled "Copy this draft" |
| I5 | confirmed | one-line: openAgent upgrades mermaid like other mdBlock modals |
| I6 | low | no change — documented false positive (`>=` line) |
| I7 | info | none |

## Handover (2026-11-17, usage limit hit)
State: worktree `.claude/worktrees/md-autodetect-copy`, branch `worktree-md-autodetect-copy`, HEAD 02594b9 (= personal/main). Main change STAGED, not committed.
A sonnet fixer was applying I1–I5 when the session stopped — it may have finished, or left partial edits. Next steps, in order:
1. `git status` / `git diff --stat` (unstaged = fixer's in-flight work); check that "## Red proofs" has I1–I5 entries. If they're missing, apply I1–I5 per the reconciliation table above.
2. Targeted tests: `unset TRACKER_AUTH; python -m unittest tests.test_draft_copy tests.test_md_fence_xss tests.test_job_headline tests.test_mermaid`.
3. Full gate one module per process (script: ~/.claude/jobs/c57b10c7/tmp/gate.sh). Known pre-existing red: tests.test_agent_map (10 failures, hardcoded 2026-07-13 dates, touches no staged file). A second module was also reported failing mid-run — identify it and check whether it is ours.
4. If the only reds are pre-existing: commit with `git commit --no-verify -F <msg>`, saying in the commit body why the hook was bypassed (msg draft: ~/.claude/jobs/c57b10c7/tmp/commit-msg.txt). Then /branch-sync, then `git push personal worktree-md-autodetect-copy`.

## Round 2 — Contract (user ask, verbatim)

> "the copy button should automatically be shared whenever some code or something with the claude/AI asks me to do it myself, slack draft messages in quotes, code, etc etc. Any links, Claude Artifacts, etc"

| Clause | Discharged by |
|---|---|
| R2-C1 "asks me to do it myself" (commands to run) | Step A (inline `code` gets Copy); fenced commands already have Copy (round 1) |
| R2-C2 "slack draft messages in quotes" | round 1 (every top-level blockquote + every fence); real data shows no third shape (below) |
| R2-C3 "code" | fences: round 1; inline code: Step A |
| R2-C4 "Any links, Claude Artifacts" | Step A (every http(s) link md() renders, artifact links included) |

## Round 2 — Plan

Base: HEAD `91b41c5` (round 1 committed). Plan author: opus. No source edited.

### Real data (conventions rule 7)

Read-only scans of assistant `text` blocks in `~/.claude/projects/*/*.jsonl`. Shape counts only, nothing quoted. Scripts: `~/.claude/jobs/c57b10c7/tmp/shape_scan.py` (latest 120 files, 5,375 text blocks) and `shape_scan2.py` (all 281 files, 12,373 main-thread text blocks).

| Gap | What the data shows | Covered today? |
|---|---|---|
| 1. "do it yourself" asks | Almost always **inline code**: 446 "run/type/paste `…`" spans and 27 `` `! cmd` `` spans (for example `` `! gcloud auth login` ``). `!` lines appear **only inside fences** (18 in fences, 0 outside). 81 of 278 fences are shell. | Fenced: yes (round 1). **Inline: no** |
| 2. Slack/email drafts | After a draft/post/send lead line, the next block is a **fence (14)** or a **`>` quote (12)**. The 35 "list" and 4 "plain" hits are all false positives on inspection: review briefs ("Before you post:" + bullets), PR status ("open as a draft at `sha`") and one inline-code command (`/remove @bot`). There are **no real plain-paragraph drafts.** | Yes, both real shapes (round 1) |
| 3. Inline code | 19,964 spans in 3,637 of 5,375 blocks, **~3.7 per block**: 15.2k identifiers, 2.9k paths, 1.9k commands. A visible button on every span would bury the text. | No |
| 4. Links | 344 markdown links and 251 bare URLs (120 files). Artifact links in main-thread text: **39 bare, 1 markdown link, 0 in inline code**. Most are on a "Published …: <url>" line. md() already turns every one into an `<a>`. Only 10 URLs sit inside inline code, and md() links those inside the `<code>` too (test_classic_markdown_and_links:608). | No |
| 5. Inline-only paths | md() alone (no mdBlock) renders: classic `.narr` rows (:2090), todo/request rows (:2132/:2138), overview goal/now (:2047-2062), decisions (:2114/:2119), notes (:2626), agent/shell `last` (:1993/:2021), CR timeline entries that the detector does not flag, CR summary/notes/decisions/ask/phone, and the headlines (`hlHtml` :2440 and the board's `headlineEl` ext_cr_board.js:2944). The headlines **unwrap anchors on purpose**: "a rail row / tile is a single click+Enter target -- no inner tab stops". | No |

### Design: one floating Copy button, shown on hover (no change to md()'s output)

A single `<button class="codecopy flcopy">` is created lazily and appended to `<body>`. When the pointer is over an inline `code` or an http(s) `<a>` that md() rendered, the button moves next to it. Clicking it copies the code's `textContent`, or the link's `getAttribute("href")`.

Why this design, and not markup inside md():
- **Rows keep a single click target.** The button is not inside the row's DOM, so its click never bubbles to the `.narr`/todo `onclick`, to the CR `timeline-entry-open` listener, or to a board tile. No `stopPropagation` plumbing, and nothing new for the round-1 `.codecopy` guard to cover.
- **md()'s HTML is unchanged.** So: no test churn (test_classic_markdown_and_links:602/:605 and test_integration:1455 pin exact link HTML); no fallout in the two anchor-unwrap regexes (`hlHtml`, `headlineEl`), which would otherwise leave an orphan button behind; and no extra icon per span, where real messages average 3.7 code spans each.
- **One mechanism covers code and links on every surface md() renders**, classic and CR alike: same document, same listener, no change to ext_cr_*.
- **Nothing becomes clickable that was not clickable before.** A click on the text still selects it, a click on a link still opens it, and a drag still selects. The brief's "must not copy while selecting" holds by construction: copying needs a click on the button.

Not chosen: click-to-copy on the `<code>` itself. It would steal clicks from the `.narr`/todo/timeline rows that use those spans as part of their open target, it fights double-click word selection, and it is invisible.

### Step A: `aitracker/web/app.js`, right after `copyCode` (:2563-2572)

```js
// Copy for inline code and links: ONE floating button in <body>, moved next to whatever inline
// `code` (fences have their own) or http(s) link md() rendered is under the pointer. It lives outside
// every row, so clicking it never opens the row/timeline entry under it. Headline rows unwrap their
// anchors to stay a single click target (hlHtml / ext_cr_board headlineEl), so they get none either.
const FLCOPY_SKIP=".shline,.cr-rail-hl,.cr-tile-line--hl,pre,.flcopy,.xterm";
function copyTargetOf(t){
  if(!t||!t.closest)return null;
  const el=t.closest('a[href^="http"]')||t.closest("code");   // a link wins: `[`x`](url)` copies the url
  if(!el||el.closest(FLCOPY_SKIP))return null;
  const text=el.tagName==="A"?el.getAttribute("href"):(el.textContent||"");
  return text?{el,text,kind:el.tagName==="A"?"link":"code"}:null;
}
let _flBtn=null,_flEl=null,_flText="",_flHide=0;
function _flOff(){ if(_flBtn)_flBtn.hidden=true; _flEl=null; }
function _flShow(c){
  if(!_flBtn){ _flBtn=document.createElement("button"); _flBtn.type="button"; _flBtn.className="codecopy flcopy";
    _flBtn.onclick=()=>copyFloat(_flBtn,_flText); document.body.appendChild(_flBtn); }
  if(_flEl===c.el&&!_flBtn.hidden)return;
  _flEl=c.el; _flText=c.text;
  const rs=c.el.getClientRects(), r=rs.length?rs[rs.length-1]:c.el.getBoundingClientRect();   // wrapped code: its last line
  const lbl=c.kind==="link"?"Copy link":"Copy";
  _flBtn.innerHTML=ico('copy')+" Copy"; _flBtn.title=lbl; _flBtn.setAttribute("aria-label",lbl);
  _flBtn.style.left=Math.max(4,Math.min(innerWidth-80,r.right+4))+"px"; _flBtn.style.top=Math.max(4,r.top-3)+"px";
  _flBtn.hidden=false;
}
function copyFloat(btn,text){
  if(!text)return;
  const done=()=>{btn.classList.add("ok");btn.innerHTML=ico('check')+" Copied";setTimeout(()=>{btn.classList.remove("ok");_flOff();},900);};
  const fb=()=>{const t=document.createElement("textarea");t.value=text;fallbackCopy(t,done);};   // fresh textarea: same iOS-safe path as pendingCopyPrompt
  if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done).catch(fb); else fb();
}
document.addEventListener("mouseover",e=>{
  if(_flBtn&&_flBtn.contains(e.target)){clearTimeout(_flHide);return;}   // pointer moved onto the button: keep it
  const c=copyTargetOf(e.target); clearTimeout(_flHide);
  if(c)_flShow(c); else _flHide=setTimeout(_flOff,250);                    // 250 ms grace to travel from text to button
});
document.addEventListener("scroll",_flOff,true);   // fixed-position button: any scroll (page, modal, CR pane) hides it
window.copyTargetOf=copyTargetOf;
```

Notes:
- **Signatures:** `copyTargetOf(el) -> {el,text,kind:"code"|"link"} | null`, `copyFloat(btn,text)`, and the private helpers `_flShow(c)` / `_flOff()`. No other function changes.
- **XSS:** the copied text goes only to the clipboard (`writeText`, or a textarea's `.value`). The button's `innerHTML` is static (`ico()` plus a literal word). The label goes through `.title`/`setAttribute`. No raw text ever reaches `innerHTML`. `getAttribute("href")` returns md()'s already-escaped href with entities decoded (`&amp;` becomes `&`), which is the URL the user wants. `^="http"` keeps out anything that is not http(s). md() only emits http(s) links anyway.
- **Feedback** is a word ("Copied") plus `.ok` colour, the same as `copyCode` and not colour alone. "Copied" shows only when the copy really happened, because `fallbackCopy` calls `done` only on success.
- **Re-render:** the poll repaints every 2 s and can detach `_flEl`. The next `mouseover` re-targets or hides the button, so no mutation observer is needed.
- **Touch:** a tap on inline code fires the emulated `mouseover`, so the button appears and a second tap copies. A tap on a link navigates, as today. The OS long-press "Copy link" still works. Known gap: no in-app link Copy on touch.
- **Keyboard:** the button is a real `<button>` with an aria-label, but it is not in the tab order: it follows the pointer, and putting thousands of spans in the tab order is worse. Keyboard users keep the native ways to copy (select plus Cmd/Ctrl-C, and the link context menu). Known gap, documented.

### Step B: `aitracker/web/app.css`, after `.codecopy.ok` (:408)

```css
.flcopy{position:fixed;top:auto;right:auto;z-index:4100;padding:3px 7px;font-size:10px}   /* the floating inline Copy: above every overlay (max z 4000) */
```
It inherits the `.codecopy` look. In Control Room the button lives in `<body>`, outside the `.cr` root, so the `.cr .codecopy` theme does not apply and it shows the app.css look. That mismatch is cosmetic and accepted. Re-check that the file has no stray `*/` (memory: one bad CSS comment kills the rest of the style tag).

### Step C: README.md:187 (the Narration capability row)
Append one clause: "…and every inline `code` span and link (Claude Artifacts included) shows a **Copy** on hover."

### Sibling paths
- Classic, CR detail, CR dialogs, the Agent modal and `.md` previews all share one document, so the one listener covers them. **No ext_cr_*.js change.**
- `mdSafe` surfaces (agent/shell `last`) are covered too, through the same `<code>`/`<a>`.
- Not covered: `popOut()` windows, which copy styles but no scripts (the existing fence Copy already does nothing there), and terminals (`.xterm` is skipped).

### Tests: `tests/test_draft_copy.py` (extend DRIVER and add a class; no new file)

Add a tiny fake-element factory to the DRIVER: `fk(tag, {href, text, cls}, parent)`. Its `closest(sel)` walks self then parents and matches comma-split selectors by tag (`code`, `pre`), by `.class`, or by `a[href^="http"]`. Then:
- `OUT["ct"]` = `copyTargetOf` over these cases, mapped to `[kind, text]` or null:
  1. `code` "! gcloud auth login" → `["code","! gcloud auth login"]`
  2. `code` inside `pre` → null
  3. `a` href `https://claude.ai/code/artifact/x` → `["link", that href]`
  4. `code` inside such an `a` → `["link", href]`
  5. `code` inside `.shline` → null; inside `.cr-tile-line--hl` → null; inside `.cr-rail-hl` → null
  6. `a` href `#frag` → null
  7. empty `code` → null
  8. a plain `span` → null
- `copyFloat(fakeBtn, "x")` with the clipboard stub records `"x"`. With no clipboard, the fallback builds a fresh textarea whose value is `"x"`, and "Copied" shows only when execCommand returns true. Reuse the existing `made`/`execLog` stubs.
- `_flShow({el: fk with getClientRects → [{right:100, top:50}], text:"t", kind:"link"})`, with `document.createElement`/`body.appendChild` stubs and `innerWidth=800`. Expect className `codecopy flcopy`, type `button`, aria-label `Copy link`, `hidden === false`, left `104px`, top `47px`. Calling `_flOff()` then sets `hidden === true`.
- `WiringTests.test_inline_copy_listener_is_wired`: the page contains `document.addEventListener("mouseover"` and `document.addEventListener("scroll",_flOff,true)`, and the page CSS contains `.flcopy{position:fixed`.
- **Red proofs** (scoped Edit revert, never `git stash`), each recorded under "## Red proofs":
  - drop `pre` from `FLCOPY_SKIP` → case 2 is not null
  - drop `.shline` → case 5 is not null
  - swap the link/code order in `copyTargetOf` → case 4 is `code`
  - remove `if(ok)` in the fallback path → the false-success assertion fails (already pinned)
  - remove the `aria-label` line → the `_flShow` assertion fails
  - delete the listener → the Wiring test fails
  - delete the `.flcopy` CSS → the Wiring test fails
- A load-time throw in the new top-level code would fail `DraftCopyTests.setUpClass`, because the harness runs the whole app.js. That covers the load-time hazard in the memory note for app.js. CSS is covered by the Wiring needle only.

### Sequencing
1. Step A (app.js): the logic, with nothing else depending on it.
2. Step B (CSS): visible only after A.
3. Tests, each red-proved.
4. README (Step C).
5. Targeted modules: `unset TRACKER_AUTH; python -m unittest tests.test_draft_copy tests.test_classic_markdown_and_links tests.test_md_fence_xss tests.test_page_css`.
6. Full gate, one module per process.
7. `make serve` restart: this is a **UI change**, so the page is baked at startup.

### Risky spot + fallback
**Risk: the floating button misplaces or lingers.** A fixed position inside scrolling modals and CR panes, the 2 s repaint, and wrapped inline code are the cases that can go wrong. Mitigations already in the plan: hide on any scroll (capture), re-target on every `mouseover`, use the last client rect for wrapped spans, and a 250 ms grace period.

**Fallback:** if it still misbehaves in manual testing, switch links only to an always-visible inline button that md() emits after each `</a>`. That means `stopPropagation` in its onclick, extending both anchor-unwrap regexes to drop it, and updating test_classic_markdown_and_links:602/:605. Inline code stays on the floating button.

### Known gaps (documented; no work)
- **Plain-paragraph drafts:** the real data has none. Every real draft is a fence or a `>` quote.
- **md() italics inside code:** md() runs `*italic*` across inline code (`` `rm *.pyc *.pyo` `` renders `<em>`), so Copy returns the text without those asterisks. This is an existing render bug in md(), not new here. Fix it separately if it bites (protect code spans before the italics pass).
- **Touch link Copy and keyboard reach** (above). Popout windows.

### Decisions for the user
1. **Floating hover button (recommended) vs. visible inline buttons.** Recommendation: floating. It is one mechanism, md()'s HTML does not change, rows stay single targets, and messages with ~4 code spans each stay clean. The alternative, a small always-visible Copy after every link with click-to-copy on code, is more discoverable and works on touch for links, but it touches md(), both unwrap regexes and two pinned link tests, and it steals row clicks.
2. **Scope: everywhere md() renders except the three headline rows (recommended) vs. reading surfaces only (modals and CR detail).** Recommendation: everywhere except headlines. The button sits outside the row DOM, so a one-line narration row can copy a command without being opened, while the dense session/rail/tile headlines, which already refuse inner targets, stay quiet. The alternative needs an allowlist of about 15 container selectors that drifts as surfaces are added.


## Round 2 — Review

Reviewer: opus, adversarial (assumed the plan is wrong). Base `91b41c5`. No source edited. Probe: `~/.claude/jobs/c57b10c7/tmp/r2_probe.js` extracts md() verbatim from app.js and runs it in node.

**Verdict:** the design holds. One floating button, outside the row DOM, with md()'s link HTML unchanged, is the right shape for 3.7 code spans per message. What does not hold is the plan's claim that "nothing changes by construction." The button sits on top of live text the moment it appears, which steals row clicks and drag-selections. On touch it swallows taps. And the plan leaves out the one bug that makes Copy return the wrong text. 1 High, 3 Medium, 4 Low, 2 Info.

| # | Sev | Finding |
|---|---|---|
| F1 | **High** | md() runs `*italic*` / `**bold**` inside inline code, so Copy returns a different command |
| F2 | Med | Touch: WebKit swallows the first tap on a row whose tap lands on inline code |
| F3 | Med | The instant overlay steals row clicks and blocks drag-selection; it lingers over a modal the click opened |
| F4 | Med | A link nested in code (`` `curl "https://…"` ``) copies only the URL, not the command |
| F5 | Low | A detached or clipped target puts the button at (4,4) or below the row |
| F6 | Low | Classed `<code>` that already has its own Copy (CR tunnel rows) gets a duplicate that copies placeholder text |
| F7 | Low | The "Copied" flash is cut short by the 2 s repaint's re-hover, and its timer hides a re-targeted button |
| F8 | Low | The touch and keyboard claims in the plan's notes are wrong or muddled. The README must state the gap |
| F9 | Info | Overbuilt: `window.copyTargetOf` export; `kind`-dependent label only partly used |
| F10 | Info | Probe 1 (discoverability) and probe 4 (copy source) verdicts. No defect |

### F1 (High): asterisks inside inline code are eaten, so Copy hands over a wrong command
- **Where:** `aitracker/web/app.js:145-152`. The `` `code` `` pass runs first, then `**bold**` (:146), then `*italic*` (:152), and both later passes run over the `<code>` content.
- **Repro (node, md() taken verbatim):**

  | Input | Expected | Actual |
  |---|---|---|
  | `` run `rm *.pyc *.pyo` now `` | `<code>rm *.pyc *.pyo</code>`, Copy gives `rm *.pyc *.pyo` | `<code>rm <em>.pyc </em>.pyo</code>`, Copy gives `rm .pyc .pyo` |
  | `` `git log --format=*%h*` `` | Copy gives `git log --format=*%h*` | Copy gives `git log --format=%h` |
  | `` `a **b** c` `` (mdSafe too) | `<code>a **b** c</code>` | `<code>a <strong>b</strong> c</code> |
  | `` **bold `c*d*` x** `` | `<strong>bold <code>c*d*</code> x</strong>` | `**bold <code>c<em>d</em></code> x**`, so the bold is lost as well |

  Copy correctness is the whole feature. A copied `chmod 644 *.sh *.py` that becomes `chmod 644 .sh .py` is a silent wrong command. **In scope.** The plan's "known gap" verdict is rejected.
- **Fix direction:** keep code spans away from the emphasis passes only. Keep everything else as it is: the escape-first order, links inside code (pinned by `test_url_in_code_stays_inside_code` at test_classic_markdown_and_links:608), the italics on plain non-code text (pinned by the sanity control `test_plain_md_still_corrupts_the_same_glob_line`), and mdSafe's no-italics rule.
- **Way:** in `md()`, replace :144-146 with the following. The rest of the function is unchanged, and the link pass still runs after the restore.
  ```js
  let h=esc(s).replace(/\u0000/g,"");                                  // NUL is the parking marker below; strip any in the input
  const cs=[]; h=h.replace(/`([^`]+)`/g,(m,c)=>"\u0000"+(cs.push(c)-1)+"\u0000");   // park code spans: **/* never run inside code
  h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  ```
  …then add one line after the italics line (:152), before the link pass:
  ```js
  h=h.replace(/\u0000(\d+)\u0000/g,(m,i)=>`<code>${cs[+i]}</code>`);   // restore; links inside code are still linked below
  ```
  - **XSS:** `cs[i]` is already `esc()`-ed text. The marker carries only digits, and NUL is stripped from the input, so a forged `\u00000\u0000` cannot bring back unescaped text. It becomes a literal `0`.
  - **Proved in the probe:** `` `<script>…` `` output is identical to today's. Links inside code are identical. `*a `b` c*` and `` see *`code`* `` are identical. The plain glob line is identical. Only the code-internal cases change.
  - **Siblings:** mdSafe, mdBlock (every inline call goes through `md()`), CR `mdHtml`, `hlHtml`, and the board's `headlineEl` all call this one function. No other edit is needed.
- **Test** (in `tests/test_classic_markdown_and_links.py`, next to `TestMdSafeDropsAsteriskItalicsButKeepsEverythingElse`):
  - `md("run \`rm *.pyc *.pyo\`")` contains `<code>rm *.pyc *.pyo</code>`.
  - `mdSafe("\`a **b** c\`")` contains `<code>a **b** c</code>`.
  - ``md("**x `c*d*` y**")`` equals `<strong>x <code>c*d*</code> y</strong>`.
  - `md("\u00000\u0000 \`<b>\`")` contains no `<b>` and no `\u0000`.
  - **Red proof:** move the restore line back above the `**` pass. The first three fail.

### F2 (Med): touch, the first tap is swallowed
- **Where:** plan Step A, `document.addEventListener("mouseover",…)` and the plan note "a tap on inline code fires the emulated mouseover, so the button appears and a second tap copies."
- **Repro:** on iOS Safari, tap a classic `.narr` row (`onclick="openMsg(i)"`, app.js:2090) on its inline code. WebKit dispatches the compatibility `mouseover`. The handler un-hides the button, which is a visible content change, so WebKit's content-change observer cancels the `click`. The row does not open, and a second tap is needed.
  - The second tap lands on the code, not on the button (the button is at `r.right+4`). So the claim "a second tap copies" is false too. The user gets a one-tap regression and no copy.
  - Android sends `pointerover` with type `touch` followed by a compatibility `mouseover`, so the same handler fires there.
  - The tunnel and `viewport` meta show the dashboard is used on phones.
- **Fix direction:** show the floating button for mouse pointers only. Touch keeps exactly today's behaviour, and native long-press still offers "Copy Link" and text selection.
- **Way:** listen on `pointerover`, and return early when `e.pointerType!=="mouse"`. Use a named handler `_flOver(e)` so the test can drive it.
- **Test:** `_flOver({pointerType:"touch",target:codeEl,buttons:0})` schedules no timer and creates no button. `_flOver` with `pointerType:"mouse"` schedules one timer. **Red proof:** drop the `pointerType` guard and the touch case schedules a timer.

### F3 (Med): the instant overlay steals clicks and selections and lingers
- **Where:** plan Step A, `_flShow` called synchronously on mouseover, placed at `left=r.right+4, top=r.top-3`. That is on top of the next words of the same line.
- **Repro 1, click steal:** in a `.narr`/todo/request row (app.js:2090/2132/2138), move the pointer across `` `make check` `` and click the row text just to its right. The button has already appeared under the pointer, so the click copies and the row does not open. At ~3.7 spans per message this affects a large share of row clicks.
- **Repro 2, selection:** press on the text before a code span and drag rightward. The button pops up over the text being selected, and while the pointer is over it, hit-testing returns the button, so the selection stalls. This contradicts the plan's claim "a drag still selects."
- **Repro 3, linger:** click a row on its code span without moving. `openMsg` opens `#msgmodal`, which is z-index 50, while the button is at z 4100. The button floats over the modal until the pointer moves.
- **Fix direction:** show the button only after the pointer dwells, never while a mouse button is held, and hide it on any press outside it. Do not change the outside-the-row placement. It is what keeps rows single-target.
- **Way:**
  - Wait 300 ms before showing: `_flT=setTimeout(()=>_flShow(c,e.clientX,e.clientY),300)`. Clear `_flT` on every `_flOver`, on scroll and on pointerdown.
  - `const c=e.buttons?null:copyTargetOf(e.target)`.
  - `document.addEventListener("pointerdown",e=>{if(!_flBtn||!_flBtn.contains(e.target)){clearTimeout(_flT);_flOff();}},true)`.
- **Test:**
  - A `_flOver` with `buttons:1` schedules no show.
  - A mouse `_flOver` records a `setTimeout` delay of 300.
  - Calling `_flAway({target:outside})` sets `hidden===true`. The handlers are named, so the DRIVER calls them directly and overrides `setTimeout` after app.js loads, because it is resolved at call time.
  - **Red proofs:** remove the `e.buttons` check; remove the pointerdown listener.

### F4 (Med): a link inside code wins, so `curl` commands lose everything but the URL
- **Where:** plan `copyTargetOf`, `t.closest('a[href^="http"]')||t.closest("code")`.
- **Repro:** md() links URLs inside code, so `` `curl -s "https://x.y/a?b=1&c=2"` `` becomes `<code>curl -s "<a href=…>https://x.y/a?b=1&amp;c=2</a>"</code>` (probe). With the pointer over the URL part, the link wins and Copy gives `https://x.y/a?b=1&c=2`. Expected: the whole command `curl -s "https://x.y/a?b=1&c=2"`. Real data has 10 such spans in 120 files.
- **Fix direction:** the outer element wins. `` [`x`](url) `` (a contains code) still copies the URL. A code span that contains a link copies the whole code.
- **Way:** `const a=t.closest('a[href^="http"]'), k=t.closest("code"); const el=a&&k?(a.contains(k)?a:k):(a||k);`. The fake element needs `contains`.
- **Test:** add case 4b: an `a` inside a `code` whose `textContent` is `curl -s "https://x"`, with the target being that `a`. Expect `["code",'curl -s "https://x"']`. Case 4 (code inside a) stays `link`. **Red proof:** restore `a||code`, and 4b turns into `link`.

### F5 (Low): detached or clipped target, button misplaced
- **Repro:**
  - `winList` (app.js:2804-2816) replaces `innerHTML` on every 2 s poll. When `_flShow` runs on a detached `el` (more likely with F3's 300 ms dwell), `getClientRects()` returns `[]`, the plan falls back to `getBoundingClientRect()`, which returns all zeros, and the button lands at (4,4), the top-left corner.
  - Separately, in `.narr .x` (app.css:385, `-webkit-line-clamp:3; overflow:hidden`), a code span that wraps from line 3 into hidden line 4 has its **last** rect on the clipped line. The button then appears over the next row.
- **Fix direction:** never position from a rect that does not exist, and place the button at the line the pointer is on.
- **Way:** `_flShow(c,x,y)`: `if(!c.el.isConnected)return; const rs=[...c.el.getClientRects()]; if(!rs.length)return; const r=rs.find(q=>y>=q.top&&y<=q.bottom)||rs[rs.length-1];`. Drop the `getBoundingClientRect` fallback.
- **Test:**
  - `_flShow` with a fake `el` that has `isConnected:false`, or `getClientRects()` returning `[]`, leaves the button hidden or not created.
  - With two rects and y on the first, `top` comes from the first rect.
  - **Red proof:** drop the `rs.length` guard.

### F6 (Low): duplicate Copy on classed code, and placeholders copied
- **Where:** `ext_cr_dialogs.js:2086/2173/2184` render `<code class="cr-mono cr-tunnel-cmd">` next to their own `copyBtn`. Their placeholder text is `connecting…` / `(set a Tunnel URL above first)`. `:921` renders `code.cr-envchip`.
- **Repro:** open Config → Tunnel and hover the URL. Two Copy buttons appear. While the URL is still connecting, the floating one copies `connecting…`.
- **Fix direction:** md() emits only **classless** `<code>` and `<a>` (app.js:145/162/165). Target only those. Classless UI code (for example `make tunnel` in a note) stays covered.
- **Way:** in `copyTargetOf`, `if(!el||el.className||el.closest(FLCOPY_SKIP))return null;`.
- **Test:** case 9: `code` with `cls:"cr-tunnel-cmd"` gives null. **Red proof:** drop `el.className`.

### F7 (Low): the Copied flash is cut short
- **Repro:** click the button, then within 900 ms the 2 s repaint makes Chromium re-dispatch hover (or the user nudges onto another span). `_flShow` rewrites `innerHTML` to "Copy", and the pending `done` timer then hides the newly targeted button.
- **Fix direction:** hold the button still while it shows "Copied".
- **Way:** the first line of `_flShow`: `if(_flBtn&&_flBtn.classList.contains("ok"))return;`.
- **Test:** add `ok` to the fake button's class list, call `_flShow` with another target, and expect `_flText` unchanged. Implementation note: the preamble's `classList.contains` always returns false, so the DRIVER's button stub needs a real set-backed classList.

### F8 (Low): the plan's claims about its own gaps are wrong
- **Where:** the plan's Notes, "Touch" and "Keyboard".
- **Fix direction:**
  - Correct the touch note to what is true after F2: no floating Copy on touch, by design; native long-press is the route.
  - Add one sentence to the README row in Step C: "(mouse only; on touch, long-press as usual)".
  - Keyboard: no change. It is a known gap, documented as the plan says.
- **Test:** none (documentation).

### F9 (Info): overbuilt bits
- **Fix direction:**
  - `window.copyTargetOf=copyTargetOf;` is unneeded. The harness concatenates `_APP_JS_STUB_PREAMBLE + app.js + DRIVER` into one script, so top-level function declarations are already visible to the DRIVER. Drop the line.
  - The pixel-exact `left 104px / top 47px` assertion is fine to keep, because it pins the clamp maths.
  - Nothing else in the plan is wider than the ask. The README clause is one line, and no ext_cr file changes.
- **Test:** none.

### F10 (Info): verdicts on probes 1, 4 and 5
- **(1) Does hover meet "automatically shared"?**
  - **Yes for code and ordinary links.** Every span and link gets Copy with no setup. An always-visible glyph on ~3.7 spans per message fails the clutter test. Click-to-copy on code would steal the `.narr`/todo/timeline row clicks, or it would need a container allowlist that drifts as surfaces are added.
  - **For Claude Artifacts** an always-visible chip is defensible: they are named explicitly, they are rare (39 in all history), and they are high-value. It costs about 10 lines: md() appends a `button.codecopy.lnkcopy` after artifact URLs, a capture-phase delegated click handler with `stopPropagation`, both anchor-unwrap regexes (app.js:2440 and ext_cr_board.js:2948) strip it, and two tests.
  - Its benefit over hover is mainly touch, where native long-press "Copy Link" already exists. Put to the user as decision 3, recommendation **no** for this round.
- **(4) Copy source:**
  - `getAttribute("href")` decodes `&amp;` back to `&` (HTML attribute char-ref decoding). md() builds the href from `esc()`-ed text, so the copied URL equals the source URL exactly. A literal `&amp;` in the source stays `&amp;`, which is faithful.
  - Code `textContent` decodes `&lt;` back to `<`. Correct, once F1 is fixed.
  - `[label](url)` copies the href, not the label. That is the same as the browser's native "Copy link address", and the button says "Copy link". OK.
- **(5) Exclusions:**
  - Headlines (`.shline`, `.cr-rail-hl`, `.cr-tile-line--hl`): right.
  - `pre`: right. It covers fences, the mermaid fallback and `.md` previews, which all have their own Copy.
  - **Do not** exclude blockquotes: copying one command out of a draft quote is useful, and the quote's own Copy copies the whole quote.
  - Add F6's classless rule.
  - `#ov_hl` (the overview headline, anchors kept) stays included. It is a card, not a row target.

## Round 2 — Clean plan

Same design as "## Round 2 — Plan": one lazily created floating `<button class="codecopy flcopy">` in `<body>`, and md()'s link HTML unchanged. The accepted fixes are F1–F7 and F9. Sequencing: **F1 first**, because Copy is only as correct as the text it reads.

### Step 0 (F1): `aitracker/web/app.js` `md()` (:143-167): park code spans before the emphasis passes
Use the exact lines in F1 → Way. This is the only edit to md(). Links inside code, escape-first, and mdSafe's rule are unchanged.

### Step A: `aitracker/web/app.js`, after `copyCode` (:2563-2572)
```js
// Copy for inline code and links: ONE floating button in <body>, shown after a short hover (mouse only) next
// to the md()-rendered (classless) inline `code` or http(s) link under the pointer. It lives outside every row,
// so clicking it never opens the row under it. Headline rows (anchors unwrapped, one click target) and <pre>
// (fences have their own Copy) are skipped. Touch: none by design -- WebKit would swallow the row's first tap.
const FLCOPY_SKIP=".shline,.cr-rail-hl,.cr-tile-line--hl,pre,.xterm";
function copyTargetOf(t){
  if(!t||!t.closest)return null;
  const a=t.closest('a[href^="http"]'), k=t.closest("code");
  const el=a&&k?(a.contains(k)?a:k):(a||k);           // the OUTER one: [`x`](url) -> url; `curl https://...` -> the command
  if(!el||el.className||el.closest(FLCOPY_SKIP))return null;   // md() emits classless <code>/<a>; classed ones have their own Copy
  const link=el.tagName==="A", text=link?el.getAttribute("href"):(el.textContent||"");
  return text?{el,text,kind:link?"link":"code"}:null;
}
let _flBtn=null,_flEl=null,_flText="",_flHide=0,_flT=0;
function _flOff(){ if(_flBtn)_flBtn.hidden=true; _flEl=null; }
function _flShow(c,x,y){
  if(_flBtn&&_flBtn.classList.contains("ok"))return;                 // hold still while it says "Copied"
  if(!c.el.isConnected)return;                                        // the 2 s repaint detached it
  const rs=[...c.el.getClientRects()]; if(!rs.length)return;
  const r=rs.find(q=>y>=q.top&&y<=q.bottom)||rs[rs.length-1];         // wrapped code: the line under the pointer
  if(!_flBtn){ _flBtn=document.createElement("button"); _flBtn.type="button"; _flBtn.className="codecopy flcopy";
    _flBtn.onclick=()=>copyFloat(_flBtn,_flText); document.body.appendChild(_flBtn); }
  if(_flEl===c.el&&!_flBtn.hidden)return;
  _flEl=c.el; _flText=c.text;
  const lbl=c.kind==="link"?"Copy link":"Copy";
  _flBtn.innerHTML=ico('copy')+" Copy"; _flBtn.title=lbl; _flBtn.setAttribute("aria-label",lbl);
  _flBtn.style.left=Math.max(4,Math.min(innerWidth-80,r.right+4))+"px"; _flBtn.style.top=Math.max(4,r.top-3)+"px";
  _flBtn.hidden=false;
}
function copyFloat(btn,text){
  if(!text)return;
  const done=()=>{btn.classList.add("ok");btn.innerHTML=ico('check')+" Copied";setTimeout(()=>{btn.classList.remove("ok");_flOff();},900);};
  const fb=()=>{const t=document.createElement("textarea");t.value=text;fallbackCopy(t,done);};
  if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done).catch(fb); else fb();
}
function _flOver(e){
  if(e.pointerType!=="mouse")return;                                  // touch/pen: no floating button (F2)
  if(_flBtn&&_flBtn.contains(e.target)){clearTimeout(_flHide);return;}
  clearTimeout(_flT); clearTimeout(_flHide);
  const c=e.buttons?null:copyTargetOf(e.target);                      // mid-drag (selecting): never pop over the text
  if(c)_flT=setTimeout(()=>_flShow(c,e.clientX,e.clientY),300); else _flHide=setTimeout(_flOff,250);
}
function _flAway(e){ if(!_flBtn||!_flBtn.contains(e.target)){clearTimeout(_flT);_flOff();} }
document.addEventListener("pointerover",_flOver);
document.addEventListener("pointerdown",_flAway,true);                // a press elsewhere (row click, drag start) hides it
document.addEventListener("scroll",()=>{clearTimeout(_flT);_flOff();},true);
```
- **Signatures:**
  - `copyTargetOf(t) -> {el,text,kind:"code"|"link"}|null`
  - `copyFloat(btn,text)`
  - `_flShow(c,x,y)`, `_flOff()`, `_flOver(e)`, `_flAway(e)`
  - No `window.` export (F9).
- **XSS:** unchanged from the plan. Copied text goes only to the clipboard. The button's `innerHTML` is static, and the label goes through `title`/`setAttribute`.

### Step B: `aitracker/web/app.css`, after `.codecopy.ok` (:408)
Unchanged from the plan: `.flcopy{position:fixed;top:auto;right:auto;z-index:4100;padding:3px 7px;font-size:10px}`. Grep the file for a stray `*/` afterwards.

### Step C: README.md:187
Append: "…and every inline `code` span and link (Claude Artifacts included) shows a **Copy** when you hover it (mouse; on touch, long-press as usual)."

### Tests
**`tests/test_classic_markdown_and_links.py`**
- The four F1 assertions, each red-proved.

**`tests/test_draft_copy.py`**
- Extend the DRIVER with `fk(tag,{href,text,cls,rects,connected},parent)`, which implements `closest` (tag, `.class`, `a[href^="http"]`), `contains`, `getClientRects` and `isConnected`.
- After app.js loads, override `setTimeout` with a recorder, and call the named handlers directly. Then add these cases:
  - **`copyTargetOf`:** plan cases 1–8, plus 4b (link nested in code gives `code` with the whole command) and 9 (classed code gives null).
  - **`copyFloat`:** clipboard path, and the fallback path with "Copied" only on success. Both as planned.
  - **`_flShow`:**
    - The plan's pixel case, with y inside the rect.
    - A two-rect case where `top` comes from the rect under y.
    - Detached, or no rects: no button.
    - `ok` held: `_flText` unchanged.
  - **`_flOver`:**
    - touch: no timer
    - `buttons:1`: no show timer
    - mouse: one timer of 300 ms
  - **`_flAway`:** a target outside the button hides it.
- **`WiringTests.test_inline_copy_listener_is_wired`:** the page contains `addEventListener("pointerover",_flOver)`, `addEventListener("pointerdown",_flAway,true)` and `.flcopy{position:fixed`.

**Red proofs** (scoped Edit revert, never `git stash`), each recorded under "## Red proofs":
- The plan's seven.
- F1: restore order.
- F2: drop the `pointerType` guard.
- F3: drop `e.buttons`, and drop the pointerdown listener.
- F4: restore `a||code`.
- F5: drop the `rs.length` guard.
- F6: drop `el.className`.

### Sequencing
1. Step 0 and its tests.
2. Step A.
3. Step B.
4. The `test_draft_copy` tests.
5. README.
6. Targeted: `unset TRACKER_AUTH; python -m unittest tests.test_draft_copy tests.test_classic_markdown_and_links tests.test_md_fence_xss tests.test_page_css`.
7. Full gate, one module per process.
8. `make serve` restart. This is a UI change, and the page is baked at startup.

### Risky spot + fallback
**Risk:** positioning inside line-clamped rows, CR panes and modals, and the hover race with the 2 s repaint. Step A now guards it with the dwell, the `isConnected`/`rs.length` checks, the rect under the pointer, and hide on press or scroll.

**Fallback:** unchanged from the plan. Make links an always-visible inline button, and keep code on the floating button.

### Known gaps (documented)
- No floating Copy on touch (by design, F2) or by keyboard.
- Popout windows have no scripts, which is the same as today's fence Copy there.
- Plain-paragraph drafts do not occur in the real data.
- A markdown link written *inside* inline code (`` `[t](url)` ``) copies `t`. This is the existing link-in-code rendering, and it is rare.

### Decisions for the user (restated)
1. **Floating hover button vs. visible inline buttons.** **Recommend floating**, now with a 300 ms dwell and mouse only. Visible inline buttons clutter ~3.7 spans per message, steal row clicks, and churn the pinned link HTML.
2. **Scope: everywhere md() renders except the three headline rows and `<pre>`, vs. reading surfaces only.** **Recommend everywhere-except-headlines**, plus the classless rule (F6). A reading-surfaces allowlist would drift as surfaces are added.
3. *(new)* **Always-visible Copy chip after Claude Artifact links** (about 10 lines: md(), a delegated capture click handler, and both unwrap regexes). **Recommend no for this round.** Hover already covers artifact links on desktop, and on touch the native long-press "Copy Link" does the job. Take it if you copy artifact links from the phone often.

## Round 2 — Reconciliation (main thread, 2026-11-17)
| # | Finding | Verdict | Action |
|---|---|---|---|
| F1 | md() runs bold/italic inside inline code (app.js:145-146) — copied `rm *.pyc` loses `*` | confirmed (re-read app.js:145-146) | accept — Step 0, lands first |
| F2 | touch: first tap swallowed | confirmed | accept — mouse-only (`pointerType==="mouse"`), the cheaper fix |
| F3 | instant button covers text / steals clicks & drags | confirmed | accept — 300 ms hover delay, never while a button is held, hide on outside press |
| F4 | URL inside a code span copies only the URL | confirmed | accept — outer code wins |
| F5 | detached target → button at (0,0); clamped wrap | confirmed | accept `isConnected` + non-empty-rect guard only; "line under pointer" positioning cut as wider than the defect |
| F6 | duplicates Config tunnel rows' own Copy | confirmed | accept — classless `<code>`/`<a>` only |
| F7 | repaint cuts "Copied" flash | low | no change — cosmetic |
| F8 | README/touch notes wrong | confirmed | accept — "mouse only" in README |
| F9 | `window.copyTargetOf` export unneeded | confirmed | accept — drop |
| F10 | hover meets "automatically"; href/entity decoding fine | info | none |

## Round 2 — User decisions (2026-11-17)
- Copy style: **hover button** (300 ms, mouse only) per the Round 2 Clean plan + reconciliation above.
- Artifacts: **yes, visible chip** — implement the reviewer's F10 design: md() appends a `button.codecopy.lnkcopy` after claude.ai/artifact/… and claude.ai/code/artifact/… links; the chip copies its preceding anchor's href at click time (no URL duplicated into an attribute); capture-phase delegated click with stopPropagation so the row doesn't open; both anchor-unwrap regexes (app.js ~2440 hlHtml, ext_cr_board.js ~2948 headlineEl) strip the chip too; two tests.
- Sign-off: **go ahead**.

## Round 2 — Implementation status
- [x] Step 0 md() code-span protection (F1)
- [x] hover Copy (Clean plan + F2–F6, F8, F9)
- [x] artifact chip
- [ ] gate, commit, branch-sync, push

## Round 2 — Red proofs
Each fix reverted with a scoped swap (never `git stash`), the module run, then restored. All 20 went RED:
- F1 restore line moved above the `**` pass -> test_asterisks_inside_code_are_kept
- NUL strip dropped -> test_forged_marker_and_html_in_code_stay_inert
- F2 pointerType guard dropped -> test_hover_is_mouse_only_delayed_and_not_mid_drag
- F3 e.buttons guard dropped -> same test; pointerdown listener dropped -> wiring/setUpClass; 300 ms delay -> 0 -> same hover test
- F4 `a||code` restored -> test_link_inside_code_copies_the_whole_command
- F5 rs.length guard dropped -> setUpClass; isConnected guard dropped -> test_detached_or_rectless_target_makes_no_button
- F6 className guard dropped; skip list dropped -> test_skips_classed_headline_pre_nonhttp_and_empty
- "Copied" hold dropped -> test_copied_flash_holds_the_button
- fallback reports success on failure -> test_copy_text_clipboard_and_honest_fallback
- chip stopPropagation dropped; wrong href; non-capture listener -> test_artifact_chip_copies_href_and_swallows_the_click / setUpClass
- chip removed from md() -> test_artifact_link_gets_chip_right_after_the_anchor
- hlHtml unwrap regex without chip -> test_headline_unwrap_strips_the_chip_too
- ext_cr_board unwrap regex without chip -> test_board_headline_unwrap_regex_strips_the_chip
Known: a code span that contains an artifact URL also contains the chip's text in `textContent` (hover Copy would append "Copy"); rare, not handled.

## Round 2 — Implementation review (opus, adversarial, 2026-11-17)
Method: staged diff read per file; old-vs-new md()/mdSafe()/mdBlock() output diffed over a 36-input corpus (HEAD app.js vs staged); an in-memory mutation harness re-ran `TestCodeSpansAndArtifactChip` + `FloatingCopyTests` against 13 mutated copies of app.js (no source edits); targeted modules (test_draft_copy, test_classic_markdown_and_links, test_md_fence_xss, test_page_css: 83 OK) plus test_cr_detail_agents_pill_and_markdown, test_cr_dialogs_markdownfork_and_scrim, test_list_headline_ui, test_mermaid, test_header_and_cost_ui, test_cr_registry_fields: all OK. Probes: /Users/pritammondal/.claude/jobs/c57b10c7/tmp/{probe.py,mut.py}.

### I1 — MEDIUM: the chip's "Copy" label is a real text node, so it leaks into every text-based copy
- **Defect:** app.js:160 emits `<button …lnkcopy…>Copy</button>` right after the anchor. Its text joins the surrounding text in `innerText` and `textContent`, with no separator, because the button is inline-block.
- **Repro (a):** this is the worst case, because the Copy button already exists. In the message modal, press Copy (`copyModal('msgbody')`, app.js:2541-2543, `innerText`) on `see https://claude.ai/artifact/abc now`.
  - Actual clipboard: `see https://claude.ai/artifact/abcCopy now`, a broken URL.
  - Expected: `…/abc now`.
- **Repro (b):** the "known gap" is real. `` `https://claude.ai/artifact/abc` `` renders `<code><a …>…abc</a><button …>Copy</button></code>`, per the probe output. Hover Copy then takes the code's `textContent`.
  - Actual: `https://claude.ai/artifact/abcCopy`.
- **Repro (c):** the flag-note context reads `$("nowtext").textContent` (app.js:2798), so it picks up `…abcCopy`.
- **Repro (d):** select the text across the link and press Cmd+C. The copied text includes "Copy".
- **Fix direction:** the chip carries no text node, and its label comes from CSS generated content. `innerText` and `textContent` exclude pseudo-element content, so (a)–(d) are all fixed at once.
  - Must NOT change: the URL stays out of any attribute; the link HTML stays the same; the unwrap regexes stay as they are (`[^<]*` already matches an empty label); `title` and `aria-label` stay, so the accessible name is kept.
- **Way:**
  1. app.js:160: change the chip string to `<button type=button class="codecopy lnkcopy" title="Copy link" aria-label="Copy link"></button>`.
  2. app.css, after `.lnkcopy{…}` (:410): add `.lnkcopy::after{content:"Copy"}.lnkcopy.ok::after{content:"Copied"}`.
  3. `_lnkCopyClick` (app.js ~2626): change `done` to `()=>{b.classList.add("ok");setTimeout(()=>b.classList.remove("ok"),1200);}` and drop both `textContent` writes.
- **Test (red before):**
  - In `TestCodeSpansAndArtifactChip`, add `OUT["plain_text"]=md("see "+ART+" now").replace(/<[^>]+>/g,"")` and `OUT["code_text"]=md("`"+ART+"`").replace(/<[^>]+>/g,"")`. Assert they equal `"see "+ART+" now"` and `ART`.
  - Update the chip literal in `test_artifact_link_gets_chip_right_after_the_anchor` to the empty-label form.
  - In the FLOAT_DRIVER chip case, record `classList.add` arguments. Assert `"ok"` was added and `chip.textContent` is still `"Copy"`, which shows it was never written.
  - Add `.lnkcopy::after{content:"Copy"}` to `test_listeners_are_wired_in_the_page`.

### I2 — LOW: the floating "Copy link" stacks on top of the artifact chip
- **Defect:** `copyTargetOf` (app.js:2582-2588) accepts the classless artifact anchor. `_flShow` then places the button at `r.right+4`, which is exactly where `.lnkcopy` (`margin-left:4px`) renders. The result is two Copy controls on top of each other.
- **Second case:** hovering the chip itself inside a code span (target = the chip, `closest("code")` = the span) pops the floating button over the chip.
- **Fix direction:** no floating button for a link that already has its chip, or for the chip itself. Must NOT change: other links and code (including code that contains an artifact link) keep hover Copy.
- **Way:**
  - In `copyTargetOf`, after `if(!t||!t.closest)return null;`, add `if(t.closest(".lnkcopy"))return null;`.
  - After `el` is computed, add `if(el.tagName==="A"&&el.nextElementSibling&&/\blnkcopy\b/.test(el.nextElementSibling.className||""))return null;`.
- **Test (red before):**
  - In FLOAT_DRIVER, give `fk` a `nextElementSibling` option, and teach its `closest` the `.lnkcopy` selector.
  - Add `OUT["chip_anchor"]=copyTargetOf(fk("a",{href:"https://claude.ai/artifact/q",next:{className:"codecopy lnkcopy"}},row))` and `OUT["on_chip"]=copyTargetOf(fk("button",{cls:"codecopy lnkcopy"},fk("code",{text:"u"},row)))`.
  - Assert both are null in `test_skips_classed_headline_pre_nonhttp_and_empty`.

### I3 — LOW: pop-out shows a dead chip
- **Defect:** `popOut` (app.js:2629-2644) copies `body.innerHTML` and the stylesheets but no scripts. Every artifact link in a popped-out message therefore shows a "Copy" chip that does nothing.
- **Fix:** hide the chip there. Must NOT change: the main page.
- **Way:** app.css: add `.pw .lnkcopy{display:none}`. The pop-out wraps the body in `.pw`.
- **Test:** assert `.pw .lnkcopy{display:none}` is in `build_page()`, in `test_listeners_are_wired_in_the_page`. It is red before the fix.

### I4 — LOW (test gap): the floating button's onclick and the scroll-hide are unverified
- **Repro:** two mutations stay **GREEN** in the mutation harness:
  - `_flBtn.onclick=()=>copyText(c.text,…)`, a stale closure that would copy the *first* hovered span forever;
  - deleting `document.addEventListener("scroll",…,true)`.
- Neither one is among the claimed 20 red proofs. The code itself is correct today.
- **Fix:** tests only. No source change.
- **Way:** in FLOAT_DRIVER, before the ok-held block:
  - set `_flBtn=null;_flEl=null`;
  - call `_flShow({el:fk("code",{text:"A"},row),text:"A",kind:"code"})`, then `_flShow({el:fk("code",{text:"B"},row),text:"B",kind:"code"})`;
  - call `_flBtn.onclick()`;
  - record `OUT["click_copies_latest"]=copied[copied.length-1]` and assert `"B"`.
  - Also set `_flBtn.hidden=false`, call `H["scroll!"]()`, and assert `_flBtn.hidden===true`. The second part goes red when the listener is removed, because `H["scroll!"]` is then undefined and setUpClass fails.

### I5 — INFO: clamped wrap still uses the last rect
- `_flShow` uses `rs[rs.length-1]`. When a code span wraps past the 3-line clamp of `.narr .x` (app.css:385), the button lands on the clipped line below the row.
- The Round 2 reconciliation cut "line under pointer" deliberately.
- **No change.** This is a known gap. If it bites, pass `e.clientY` and pick `rs.find(q=>y>=q.top&&y<=q.bottom)`.

### I6 — INFO: md() output diff vs HEAD (36 inputs × md/mdSafe/mdBlock)
- **Intended changes only:**
  - `*`/`**` stay literal inside code (`` `*a*` ``, `` `**x**` `` in tables and headings).
  - The mis-nested `**a `b** c`` no longer emits crossed `<strong>`/`<code>` tags.
  - NUL is stripped.
  - Chips appear after artifact links only. Both shapes get one: `/artifact/` and `/code/artifact/`, over http(s). Lookalikes get none: `claude.ai.evil.test`, `/artifacts/`, and an artifact URL in a query param.
- **One side effect:** `*a `x\ny` b*` now italicizes, because the marker hides the code span's newline from the italic `[^*\n]`. It is benign. **No change.**
- **XSS:** clean on every path.
  - Every code span with HTML stays escaped.
  - `"`-breakout after an artifact URL leaves the chip static and the quote outside `href`.
  - `javascript:` links stay unlinked.
  - A forged NUL marker cannot index `cs`, because NUL is stripped first.
  - `$&`/`$1` inside code are literal, because the restore uses a function replacement.

### I7 — NIT: the scroll handler writes on every scroll
- The capture-phase scroll handler fires on every scroll, including streaming xterm output and live auto-scroll. Each time it writes `hidden=true`.
- Optional fix: `if(_flBtn&&!_flBtn.hidden)`. **No change required.**

### Verified OK (no finding)
- **Headline unwraps:** both regexes strip the anchor and its chip, including a chip inside `<code>`.
- **Click handling:**
  - The capture click handler acts only under `.lnkcopy` (`other_click_stopped=0`).
  - The classic `.narr onclick`, the CR timeline delegated click (ext_cr_detail.js:1799) and the overview Now banner never see a chip click.
  - Keyboard Enter/Space on the chip copies.
- **Markup:**
  - No md() output is ever placed inside a `<button>`, so there is no nested-button parse breakage.
  - `.codecopy` has no `display` rule, so `[hidden]` hides the floating button.
  - z-index 4100 is the page maximum (the next highest is 4000).
  - `.lnkcopy{position:static}` beats `.codecopy{position:absolute}`, because it has equal specificity and comes later. The CR `.cr .codecopy` rules are colour-only.
- **Floating button:**
  - Touch and pen are ignored.
  - The pointerdown and scroll handlers are safe when the button does not exist yet.
  - The listeners are module-level and added once, so nothing leaks.
- **No doubled Copy controls:**
  - Quote/draft Copy reads `.cpsrc` (raw), so the chip does not affect it.
  - Fences are skipped (`pre`).
  - Config tunnel rows use classed code, so they are skipped.
- **Red proofs:** 11 of 13 independent mutations went RED. The 2 GREEN ones are I4, which is not among the claimed proofs. The claimed F1, F2, F3, F4, F5, F6, chip-capture, chip-stopPropagation, chip-scope, dwell and hlHtml proofs were reproduced.

**Verdict: fix-first.** I1 is a three-line change (the chip string, two CSS rules, and the handler's `done`) that stops silent URL corruption in the existing message-modal Copy. I2, I3 and I4 are a few lines each and can land in the same pass. Then re-run the targeted modules.

## Round 2 — Implementation review reconciliation (main thread)
| # | Verdict | Action |
|---|---|---|
| I1 | confirmed — chip label is a text node, leaks into copyModal / hover-copy / Cmd+C | fix: empty button + `.lnkcopy::after{content:"Copy"}`, `.ok::after{content:"Copied"}`, handler toggles `ok` |
| I2 | confirmed | fix: copyTargetOf → null on the chip or an anchor followed by a chip |
| I3 | confirmed | fix: `.pw .lnkcopy{display:none}` |
| I4 | confirmed test gap | add the two tests (float click uses current target; scroll listener hides) |
| I5 | deliberate (round-2 F5 cut) | no change |
| I6 | info | none |
| I7 | nit | no change |

## Round 2 — Red proofs (implementation-review fixes I1-I4)
Each fix reverted by a scoped swap (no stash), module run, restored. All RED:
- I1 chip label back as text node -> RED (FAILED (failures=2))
- I1 handler writes textContent (no .ok add) -> RED (FAILED (failures=1))
- I1 ::after css removed -> RED (FAILED (failures=1))
- I2 chip self guard dropped -> RED (FAILED (failures=1))
- I2 anchor-followed-by-chip guard dropped -> RED (FAILED (failures=1))
- I3 .pw rule removed -> RED (FAILED (failures=1))
- I4 stale closure onclick -> RED (FAILED (failures=1))
- I4 scroll listener removed -> RED (FAILED (errors=1))
I5-I7: no code (per reconciliation). Chip tests pinning literal "Copy" updated to the empty-button + ::after shape.
