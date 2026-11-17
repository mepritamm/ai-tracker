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
