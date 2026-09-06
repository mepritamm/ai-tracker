# Board tiles, rail parity, and "waiting on you"

Unattended run (`/head-out`). Worktree: `.claude/worktrees/board-tiles-config`,
branch `worktree-board-tiles-config`, based on local HEAD `5dea10f`.

## The contract, verbatim

1. "the config in the board view for the number of tiles is not working from the config"
2. "the session rail needs to be of the same size width and should display similar
   information and needs to be in absolute feature parity with the control-view and the
   old default view. including the information present in there"
3. "waiting on you in the board also not working"
4. `/tracker-gap` `/tracker-push` `/head-out`

Verdict per clause below.

---

## Clause 1 — Board tiles config. DISCHARGED.

**Not** a key mismatch: Config writes `cr.boardTileCount` (`ext_cr_dialogs.js:784`) and
`boardTileCap()` (`ext_cr_board.js`) reads that exact key, fresh, clamped 3-12. The value
round-trips correctly (`Number()` -> `JSON.stringify` -> parses back a number).

**The bug was a dead control.** `writePref()` emits a `cr:pref` bus event
(`ext_cr_dialogs.js:813`). There were exactly two subscribers:
`ext_cr_boot.js:380` (handles only `cr.pollIntervalMs`) and `ext_cr_board.js` (handled only
`tracker.rail.mode`, early-returning on everything else). Nothing repainted on
`cr.boardTileCount`, so moving the slider changed a number in localStorage and left the
board on screen untouched.

Fix: the board's `cr:pref` subscription now also owns the tile cap and re-renders the board
(which redraws the cap footer via `renderBoard -> renderCapFooter`). This mirrors, one branch
above, the rail-mode subscription whose own comment calls this exact shape "the same
dead-control bug this whole change exists to remove".

Guarded against a null `lastState` (pref changed before the first poll lands) so the branch
no-ops rather than throwing and taking the rail-mode row down with it.

### Caveat the owner should read
The screenshot showed "3 of 957" with the slider at 5 — the cap was NOT the binding
constraint there. The board only tiles NON-IDLE sessions, and only 3 were non-idle, so every
cap value 3-12 shows the same 3 tiles. The slider is now live, but it will keep looking
inert whenever fewer sessions are active than the cap. If the intent is "fill the board up to
N by topping up with idle/pinned sessions", that is a deliberate reversal of doc 02's
"idle sessions never get a tile" and needs an owner ruling — NOT taken unilaterally.
Related: 5 sessions are PINNED yet none get a tile, because a pinned-but-idle session is
filtered out. Pinning is currently inert on the board.

## Clause 2 — Rail parity. DISCHARGED.

**Width.** Classic sidebar is `.side{width:300px}` (`app.css:17`); the rail was `232px`.
Three separate rules set a rail width (open, mobile overlay, and the overlay's "collapsed is
still the full row rail" case) and they must always agree, so they now all read one variable
`--cr-rail-w: 300px`. The collapsed (48px) and detail-orb (56px) widths are a different
feature and are deliberately unchanged. Stale `232px` comments updated so the file cannot
drift. NOTE: 232px was the control-room spec's own literal; this is an owner-directed
override of that spec constant.

**Information.** Gaps found against `app.js`'s `sessionRow()`, all now closed:
- project name (visible) — classic's exact ternary, not an approximation
- source label — reuses this file's OWN `toolLabel()` (already used by the tiles, wraps
  app.js's `srcLabel`/SRC map). No second copy of the source vocabulary.
- waiting/done status badge — app.js's end-state rule verbatim ("waiting" wins even while
  live; "done" gated to the live window so stale sessions don't flood the rail)
- note count — was tooltip-only, now on the row

**Bonus bug found while doing it:** `railRowMeta()` returned on the FIRST truthy of
flags/bg/age, so a flagged row silently LOST its age, and so did a row with background
agents. Classic shows them together. Now joined, never one.

Both `waiting` and `ended` ride the shared list dict (`claude.py` AND `auggie.py` both emit
them), so this lights up for both providers — no provider asymmetry.

## Clause 3 — "Waiting on you". DIAGNOSED, NOT A CODE CHANGE. See parked.

Measured on the real logs: **0 of 957** sessions have `waiting=True`.

The predicate (an `AskUserQuestion` `tool_use` whose id has no matching `tool_result`) is
correctly implemented in both providers. And the pending state IS observable on disk —
measured gaps between the tool_use and its tool_result of 84.2s, 124.7s, 168.2s, 286.3s and
472.2s prove the tool_use is flushed the instant it is emitted, independent of the answer.

So `0` is the CORRECT answer for these logs at rest: 244 of 245 asks on disk are already
answered. The single genuine orphan (`fc2c5636-...jsonl`, an ask abandoned mid-conversation)
is missed only because it sits at line 114 of 941 — outside the 96000-byte tail window
`_tail_scan()` reads (`providers/claude.py:89`).

What WAS broken in this area, and is now fixed, is the display path — see below.

## Also fixed — board filter vs agent-group tiles

`passesFilter()` carried two bugs on one line. The group branch read `t.session.open_flags`,
but an agent-group tile has NO `.session`; it aggregates several under `.sessions` (plural,
built by `agentGroups()`). So:
1. the `flagged` filter threw a **TypeError** the moment any group tile was on the board, and
2. every other filter returned a flat `false`, hiding grouped sessions from the
   `awaiting`/`working` filters — while `triageCounts()` counts exactly those sessions in the
   strip above it. That is a cell reading a non-zero count and still rendering
   "Nothing matches that filter right now."

A group tile now passes when ANY member session matches — the same question the strip's own
count asked.

---

## Verification

Every fix was proven by reverting it and watching the test go RED, then restored:
- board-tiles repaint: `renderBoardCalls` 0 != 1 without the fix
- group-tile filter: 2 failures without the fix (the TypeError case and the working case)

13 new tests in `tests/test_cr_rail_toggle.py` across:
`TestBoardSubscribesToConfigPrefChanges` (extended), `TestRailRowMetaParity`,
`TestRailWidthMatchesClassicSidebar`, `TestBoardFilterHandlesAgentGroupTiles`.

## Parked for the owner (needs a ruling, not a guess)

1. **Should the board top up to the tile cap with idle/pinned sessions?** Today it cannot
   exceed the number of non-idle sessions, which is why the slider looks inert. Reversing
   this contradicts doc 02's "idle sessions never get a tile".
2. **Should a pinned session always get a tile?** 5 pinned, 0 tiles today.
3. **Should the tail-scan window widen past 96KB so an abandoned question still reads as
   "waiting on you"?** Costs a bigger read across ~957 sessions, and it is arguable whether a
   question abandoned weeks ago is really "waiting on you".

## Restart note

UI/parse change — the page is baked at server startup (`page.build_page`). Restart with
`make serve` to see any of this; a browser reload alone is not enough.
