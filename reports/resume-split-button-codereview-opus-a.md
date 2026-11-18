# Code review A (opus): shared helpers, header, in-terminal toolbar

I ran 16 mutants against a /tmp copy, with nothing edited in the worktree. All 16 turned RED, among them: Escape without `stop()`, no pointerdown listener, restore as a no-op, fit before unhide, the loose host regex, no deny, `here` ignored, and Resume emitting `terminal:open`. The tests drive the real code.

## Findings

**1. minor: `TSPLITS` grows without bound** (`app.js:142`, `termSplit`). The keys are `ext_launch:<sid>` and `board-hero:<sid>`, and no entry is ever deleted. Every click and pointerdown runs `termSplitClose` over all of them.
- Repro: build splits a, b and c, detach a and b, then pointerdown on the body. The keys stay `[a,b,c]`; expected `[c]`.
- FIX DIRECTION: prune disconnected entries only at user-event time. Do NOT prune in `termSplit`/`termSplitSet`/`termSplitOpen`: a rebuild registers its new node before mounting it, and restore needs it.
- WAY: at the top of `_tsplitOutside`, add `for(const k in TSPLITS)if(TSPLITS[k].isConnected===false)delete TSPLITS[k];`.
- TEST: in `test_tsplit_shared` test_7, run the repro and assert `[c]`. It is RED today.

**2. minor: the menu's name is fixed** (`app.js:190`). The list is always labelled "Resume options". That is wrong for a non-resumable session ("Open externally") and for the toolbar's solo menu.
- Repro: `termSplitSet(sp,{resumable:false,ext:true})`. The list's `aria-label` is "Resume options"; expected "More Open terminal options".
- FIX DIRECTION: name the menu after its button, as in the APG pattern. Do not change the caret's name or the item labels.
- WAY: in `termSplitSet`, after `nm` is computed, add `t.list.setAttribute("aria-label",nm);`.
- TEST: in `test_tsplit_shared` test_2, assert that the list's label equals the caret's for the resumable, non-resumable and solo rows.

**3. minor: a 403 leaves the header's external item live until the next render.** `ext_cr_boot.js:803,807` call `termExtDeny()`, but nothing re-syncs the header split. Until the next render, "Resume externally" and ⌥-click stay live, and a second click gets a second 403 toast. The toolbar does re-sync (`ext_cr_term.js:572`).
- FIX DIRECTION: optional, because the gap lasts one poll. Do not add an event bus, and do not touch the probe.
- WAY: after each deny, add `var sp=TSPLITS["crd-head"]; if(sp) termSplitSet(sp,{resumable:resumable,ext:false});`.
- TEST: in `test_tsplit_header`, run the boot handler with `fetchImpl` returning 403, await, and assert `iExt.hidden` with no re-render.

**Not verified:** there was no browser check. The caret's hit box at 390px (about 24px) is unmeasured.

## Sound

- **Contract 2:** no `aitracker/*.py` changes, and the BrokenPipe guards are intact.
- **Header:** emits `session:resume`, `terminal:open` and `session:openExternal` with `ui.sid`, the same as the base.
- **Toolbar:** goes through the unchanged `_openInline` and `_openExternal`. The 409 recreate, dedupe and attach paths are untouched.
- **External:** the loopback check is exact, and a remote host sends no probe POST. The 403 latch works in the boot and toolbar paths.
- **Read-only:** one universal rule hides the split.
- **APG:**
  - caret has `aria-haspopup`, `aria-expanded` and a name that names the primary; list is `role=menu`, items are `menuitem` with `tabindex=-1`;
  - ↓ and ↑ open on the first and last item and wrap, Home and End work, and hidden items are skipped;
  - Escape closes, refocuses the caret and stops propagation, so the overlay's bubble Escape listener and `ext_vt`'s never fire; Escape from xterm passes through;
  - Tab closes, and the focus trap still works;
  - outside click and pointerdown close the menu, and a null `relatedTarget` is tolerated;
  - an item runs once and closes, with focus moved to the caret before the handler.
- **Fit:** measures after unhide, against the shell's `overflow:hidden`.
- **Specificity:** the (0,4,0) rules beat the `.crd-btn` and `.cr-term-btn` rules.
- **Tokens:** they have classic fallbacks, and the `currentColor` divider follows light and dark.
- **Checks:** `node --check` is clean, and these modules are green: `test_page_bundle`, `test_cr_readonly_ui`, `test_icons` and the 7 in-scope modules.

Verdict: SHIP. Findings 1-3 are minor and can go in one follow-up commit.
