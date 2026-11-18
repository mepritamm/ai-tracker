# Code review (sonnet, cross-cutting): Resume split button, clauses 2-8 in all four places

Clause 2: `git status --short` shows no `aitracker/*.py` (0 matches). Single-module runs green: test_tsplit_shared (22), _header (10), _toolbar (9), _classic (10), test_cr_board_resume_button (21).

## Parity table (code read, not just tests)

| Aspect | Header (ext_cr_detail.js 2373-2400) | Toolbar (ext_cr_term.js 276-290, 1127-1138) | Classic (ext_launch.js 415-434) | Board hero (ext_cr_board.js 2956-2973) |
|---|---|---|---|---|
| Builder | termSplit, key crd-head, mounted once | termSplit, key cr-term, mounted once | termSplit, key ext_launch:+cur, rebuilt per poll | termSplit, key board-hero:+id, rebuilt per list poll |
| Resumable input | termResumable(session.id or sid) | termResumable(st.sessionId) | termResumable(cur) | raw `!!s.resumable` (+ !readOnly) |
| Primary if non-resumable | Open terminal | Open terminal | Open terminal | Open terminal |
| Items | Open terminal (resumable only) + one external | same | same | same |
| External label | by resumability, via termSplitSet | same | same | same |
| External handler | session:openExternal, boot termResumable | _openExternal resume/cwd by isClaudeId | openTerm resume/cwd | session:openExternal, boot termResumable |
| Option-click | shared termSplitOn: external only if iExt visible | same | same | same, plus stopPropagation |
| Tooltip names the Option glyph | only when ext | same | same | same |
| Read-only | CSS `html.tracker-readonly .tsplit` (app.css 675) | CSS | CSS | JS skip (`readOnly ? null`) plus CSS |
| External gate | trackerIsLocal + probe (null hides) | same | same | same |
| 403 latch | boot termExtDeny; no resync | termExtDeny + _syncControlVisibility | termExtDeny + render(lastD) | boot termExtDeny; no resync |
| Caret name | "More Resume/Open terminal options"; "External terminal options" when solo | same | same | same |
| Menu alignment | shared right-aligned + _tsplitFit start-flip | same | same | same |
| Keep-open across rebuild | not rebuilt | not rebuilt | snapshot/restore | snapshot/restore |

All four draw labels, roles, keys and CSS from one block, so label, primary and gate behaviour match. Only the findings below differ.

## Findings

1. **minor. The "⌥-click" hint shows where no primary exists.**
   - Defect: app.js:214-235, `termSplitSet` never touches `t.hint`. In the attached-terminal solo mode (`here:false`, toolbar) both primaries are hidden, yet the External item still reads "Resume externally ↗ ⌥-click". The tooltip rule ("name it only when it works") is honoured for titles but not for the hint.
   - Repro: toolbar with `st.attached=true`, ext allowed → open the caret → the hint is visible, with nothing to Option-click.
   - FIX DIRECTION: hide the hint when no primary is visible. Do not remove the hint elsewhere.
   - THE WAY: in `termSplitSet`, add `t.hint.hidden=!here;`. `.tsplit [hidden]` already hides it.
   - THE TEST: in test_tsplit_shared, call Set with `{here:false, ext:true}` and assert `hint.hidden===true`. With `here:true` assert `hint.hidden===false`. Red before the fix.

2. **minor. A 403 latch leaves the external item visible in the header and on the board.**
   - Defect: boot's `termExtDeny()` (ext_cr_boot.js 802/810) only flips `TERM_EXT`. The toolbar and classic re-sync immediately. The header and board only fix themselves on the next poll, and until then the menu still offers the refused action.
   - Repro: press Resume externally on a server that answers 403 → notify shows → reopen the caret: the item is still there.
   - FIX DIRECTION: make the latch itself update live splits, so no caller needs its own re-sync. Do not add per-caller code.
   - THE WAY: in `termSplitSet`, store `t.last=s`. In `termExtDeny`, add `for(const k in TSPLITS){const sp=TSPLITS[k];if(sp._ts&&sp._ts.last)termSplitSet(sp,Object.assign({},sp._ts.last,{ext:false}));}`.
   - THE TEST: in test_tsplit_shared, build a split, Set `ext:true`, call `termExtDeny()`, and assert `iExt.hidden`. Red before the fix.

3. **minor. TSPLITS grows without bound.**
   - Defect: app.js:142/200, `TSPLITS[key]=split` is never pruned. Classic keys per `cur` and board keys per hero id accumulate as detached nodes. `termSplitClose` iterates all of them on every outside click.
   - FIX DIRECTION: prune detached entries. Do not prune in `termSplit` itself: a node just built is not yet attached, so it would prune its siblings.
   - THE WAY: in `termSplitSnapshot`, which runs before a rebuild, `if(sp.isConnected===false)delete TSPLITS[k]` instead of `continue`.
   - THE TEST: build 3 splits, detach 2, call Snapshot, and assert the registry size is 1.

4. **nit. The resumability source differs between callers.**
   - Defect: the board reads the raw `s.resumable`. The other three places and boot use `termResumable` (row flag, else id regex).
   - Today both give the same answer, because `registry.py:32` sets the flag on every row.
   - Direction: no change, a known latent gap. Document it in the PR. If it is ever unified, pass `termResumable(s.id)` into `heroSplit` and keep `!readOnly` and the awaiting gate.

## Sound

- Helper contract, ARIA wiring (haspopup / expanded / controls, menu / menuitem), the key map (Enter/Space/Arrow/Home/End/Esc/Tab), the pointerdown and click outside-close, and the null-`relatedTarget` guard.
- The board test's `closest` emulation splits the REAL selector string from `tileBaseAttrs`, so removing `[role=menu]` from the real guard turns it red.
- Strict loopback (`trackerIsLocal`) has one copy; the old unanchored regex is gone from all four places.
- Resume still emits `session:resume`; the dedupe, attach and recreate paths are untouched. Read-only is covered everywhere, and the CSS rule is the last split rule.
- NOT verified: the browser pass (the :has() z-index, 390px caret hit box, light/dark, start-flip) is marked NOT done in the log. The tile has no stacking context, so z-index 80 should paint over the next tile, but it is unverified.

Verdict: SHIP (findings 1-3 are minor and optional; 1 is the cheapest and most visible). The browser pass is still owed.
