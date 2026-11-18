# Resume split button — redesign (front-end only)

Branch: `board-resume-parity` (worktree `.claude/worktrees/board-resume-parity`), base `personal/main`.
Opened 2026-11-18. Unattended run (head-out).

## Contract (verbatim from the user)

1. "can you also make research and find better ways to put the dropdown button beside the resume button, this is a design request, research and come up with better suggestions for the dropdowns beside the resume button ?"
2. "no backend change for the above the only a design change"
3. Layout: **"B split button everywhere"** — one joined shape with a divider, a real menu button (keyboard + screen-reader correct), same items everywhere, in all three places (session header, in-terminal toolbar, classic dashboard pane).
4. External items: **"One: Resume externally ↗"** — a single external action, same label in all places.
5. Board tiles: **"Resume + ▾ caret"** — same split button as the header on the hero tile; icon-only tiles unchanged.
6. Extras: **"Consistency fixes"** (hide the split for read-only viewers in all 3 places, header respects the existing 'external not allowed' check with a strict localhost test, one style + one menu alignment) and **"⌥-click = external"** (Option-click Resume opens it externally; named in the tooltip and beside the menu item; never the only way).
7. Sign-off: "1, make sure all the stages are planned with /gap and /tracker-gap skill in mind" — implement after the plan passes review.
8. Label for non-resumable sessions: "not for auggie per say, anything which cant be there with the regular resume" — the label follows resumability, not the provider: a session that can do a regular resume gets **Resume externally ↗**; any session that cannot gets **Open externally ↗** (and its primary is Open terminal).
9. Landing: "make sure the branch/code changes in the main branch, if not then /branch-sync and hold for the /tracker-push since the other session is also doing it, do it only after the session's push is completed and then then run /branch-sync -> /tracker-push"

| Clause | Status |
|---|---|
| 1 research + suggestions | discharged (options A/B/C delivered in chat 2026-11-18) |
| 2 no backend change | discharged: no aitracker/*.py changed (verified by 3 code reviews) |
| 3 B everywhere | discharged: header, toolbar, classic (+ board hero) use one termSplit |
| 4 one external item | discharged |
| 5 hero tile Resume + ▾ | discharged; icon-only tiles unchanged |
| 6 consistency fixes + ⌥-click | discharged (24px caret size parked for the user) |
| 7 plan with /gap + /tracker-gap, then implement | discharged: plan → 2 reviews → re-review → 6 units → 3 code reviews + 2 browser checks → fixes; full gate 172/172 |
| 8 label by resumability | discharged (`termResumable`) |
| 9 land on main after the other session's push | not discharged |

## Starting facts (from the read-only map, 2026-11-18)

- Shared helper `termSplit()` / `termSplitSync()` / `termSplitClose()` in `aitracker/web/app.js` (~107-151), CSS `aitracker/web/app.css` (~657-668). Built on `<details>/<summary>`, caret is a separate pill (`gap:2px`), aria-label "More terminal actions", no menu roles, no arrow keys.
- Callers: session header `ext_cr_detail.js` (~1383-1387, visibility ~2552-2560), in-terminal toolbar `ext_cr_term.js` (~160-171, ~1140-1164, `_placeOpenHere`), classic pane `ext_launch.js` (~429-479), board tiles `ext_cr_board.js` (~2972-3030, Resume emits `session:resume` after commit 40c5665).
- Inconsistencies: header localhost regex unanchored (`ext_cr_detail.js` ~2552) vs exact in classic (`ext_launch.js` ~17); header ignores the extAllowed/403 probe; header has one External, toolbar/classic have External terminal + External resume; caret radius differs per caller; read-only hides the split only in the header (`ext_cr.css` ~521); menu alignment right (header) vs left (others); z-index 60 vs 80.
- Research (primary sources): two real `<button>`s, two tab stops; caret `aria-haspopup="menu"`, `aria-expanded`, accessible name naming the primary ("More Resume options"); `role="menu"` + `menuitem`, Enter/Space/↓ open and focus first item, ↑/↓ roving, Escape closes and returns focus to the caret, Tab closes; always-visible divider (~1-2px); menu aligned to the caret's end edge; no sticky last-used default; shortcuts named in the UI, never the only path. Sources: W3C APG menu-button, NN/g split-buttons, Atlassian split button, IBM Carbon combo button, GitHub Primer ButtonGroup, Material 3 split button, Scott O'Hara on details/summary.

## Plan

_Author: opus plan agent, 2026-11-18, revised the same day to fold in every "Folded in as" cell of the Reconciliation table below. It is grounded in the worktree at 40c5665. Line numbers are hints; locate every edit by symbol. This is the single clean plan, and an implementer does not need the reviews._

### P0. Gap framing (/gap Step 1, /tracker-gap Step 1)

- **Capability, in one line:** every Resume entry point shows ONE split button. The entry points are the session header, the in-terminal toolbar, the classic pane and the board hero tile.
  - The primary is Resume, or Open terminal when the session cannot do a regular resume.
  - It is joined to a real WAI-ARIA menu button whose menu holds the same items everywhere:
    - **Open terminal**, only when Resume is the primary;
    - **one external item**, labelled by resumability: **Resume externally ↗** or **Open externally ↗**.
  - ⌥-click on the primary runs the external item.
  - Read-only viewers never see the split.
  - The external item shows only on an exact-loopback host, and only when the server's existing 403 probe allows it.
  - Sources: clauses 3, 4, 5, 6 and 8.
- **The asymmetry (this is the gap):** four callers, with each piece of policy forked between them.
  - `termSplit` (app.js) is a `<details>` disclosure, so it has no menu semantics.
  - The resumability id regex is copied 4 times: `ext_cr_detail.js` renderHeader, `ext_cr_term.js` `isClaudeId`, `ext_launch.js` `isClaudeId` and `ext_cr_boot.js` `session:openExternal`. The board alone reads the server's `resumable` flag.
  - The local test is copied 3 times, and the header's copy is unanchored (`/^(localhost|127\.0\.0\.1)/` matches `localhost.evil.com`).
  - The 403 probe is copied twice (`ext_launch.js` `allowed/probe`, `ext_cr_term.js` `extAllowed/_probeExternal`). The header never probes.
  - Items differ by caller: the header has "External"; the toolbar and classic pane have "External terminal" + "External resume".
  - Menu alignment differs (right vs left). z-index differs (60 vs 80). Caret shape differs (an outline vs solid pill, separated by `gap:2px`).
  - Read-only hides the split only in the header.
- **Entry points:**
  - E1 header: `ext_cr_detail.js` `SKELETON` + `Detail.prototype.mount` + `renderHeader`.
  - E2 toolbar: `ext_cr_term.js` `_build` / `_syncControlVisibility` / `_syncSplit`.
  - E3 classic pane: `ext_launch.js` `render(d)`, which rebuilds the WHOLE pane (split included) on every 2 s poll, at ~472.
  - E4 board hero: `ext_cr_board.js` `sessionTile`, rebuilt on every list poll by `renderBoard`.
  - The external action for E1 and E4 routes through `ext_cr_boot.js` `on('session:openExternal')`.
- **The seam:** one set of top-level functions in `aitracker/web/app.js` plus one CSS block in `aitracker/web/app.css`.
  - Callers keep only their button classes, their handlers (which event each emits) and their `resumable` input.
  - They never re-derive markup, labels, visibility, ⌥-click, local/probe or keyboard behaviour.
- **Localhost vs remote (/tracker-gap path 5):** in-browser Resume and Open terminal are never host-gated, so they work over a tunnel or on a phone.
  - Only the external item is host-gated. That is the sanctioned OS-process-launch exception; its ponytail comment moves with the helper.
  - The gate is cosmetic. `term_launch._local_caller` / `term_gate.guard` stay the real gate.
- **No backend change (clause 2 holds):**
  - `registry.all_sessions` already sets `r["resumable"] = not p.prefix` on every list row, and the client holds those rows in app.js's top-level `sessions`.
  - The detail dict has no `resumable`, so the helper reads the list row and falls back to the existing id rule. For today's 4 providers the answer is identical.
  - External-allowed reuses the existing `POST /api/term/open {session:""}` probe (403 = off).

### P1. Unit 1: the shared API and CSS

**Unit 1 files (exclusive):**
- `aitracker/web/app.js` (the split block, ~103-151, replaced)
- `aitracker/web/app.css` (~657-668, replaced)
- `aitracker/web/ext_cr.css` (one line, ~521)
- `tests/test_icons.py` (one line, ~221)
- new `tests/_tsplit_dom.py`
- new `tests/test_tsplit_shared.py`

**Harness-agnostic rules.** These are binding (O1+S3). About 21 test modules load the real bundle through `_REAL_DOM_PREAMBLE`/`_bundle_js` (`makeReal`, `tests/test_working_glow_board.py:155-267`). That fake DOM has several limits:
- `innerHTML` never parses;
- `closest()` returns null;
- `queryAllReal` matches a single class only;
- there is no `contains` and no `document.activeElement`;
- `addEventListener` keeps one listener per type;
- `simulateClick` sends an event with no `target`, `preventDefault` or `altKey`.

So:
- `termSplit` builds with `document.createElement` / `setAttribute` / `appendChild` / `textContent` only. It never uses `innerHTML`, except an optional icon given as an HTML string, which goes into its own `span`.
- It stores every reference on the node: `split._ts = {key, res, open, caret, list, iOpen, iExt, label, hint, titles}`.
- `termSplitSet`, `termSplitOn`, `termSplitOpen`, `termSplitClose`, `termSplitSnapshot` and `termSplitRestore` **never run a selector query**. They use `_ts` and the registry below.
- Each split button carries **exactly one** listener per event type.
- Handlers tolerate a missing event, `target`, `preventDefault` or `altKey`: `e && e.altKey`, and `if (e && e.preventDefault) e.preventDefault()`.
- `document.activeElement` and `.contains` are guarded with `typeof` checks.
- Only the document-level listeners (real browsers; a no-op in `makeReal`) may use `closest`, and they find the owning split via `_tsplitOwner(node)`. That function walks `parentNode` up to a node with `_ts`.
- There are no `{`/`}` inside string or regex literals, because the tests brace-extract these functions. `document` is touched only at call time.

**Signatures.** These are top-level `function` declarations, exported on `window` like today.

```js
// Loopback test: the ONE copy. The ponytail exception comment moves here from ext_launch.js.
function trackerIsLocal(){ return location.hostname==="localhost"||location.hostname==="127.0.0.1"; }

// External-allowed: the existing probe, shared and latched.
const TERM_EXT={allowed:null,probe:null};
function termExtAllowed()   // -> true|false|null. false when !trackerIsLocal(); null kicks termExtProbe()
function termExtProbe()     // -> Promise<bool>. At most ONE POST /api/term/open {session:""} per page load;
                            //    status!==403 -> true, 403 or a rejected fetch -> false; resolves to TERM_EXT.allowed
function termExtDeny()      // TERM_EXT.allowed=false; TERM_EXT.probe=Promise.resolve(false). Any later 403 calls it.

// Resumability: the server list flag wins; the id rule is only the fallback for a row not in `sessions`.
function termResumable(id)  // !id -> false; row with boolean .resumable -> it; else !/^(auggie|augment-vscode|augment-cursor):/.test(id)

// Registry of live splits by key, so Close/Snapshot/Restore need no DOM query.
const TSPLITS={};           // key -> latest split built for that key (rebuilding a key replaces its entry)

function termSplit(o)       // -> HTMLSpanElement. o={key, primaryCls, caretCls, resumable,
                            //    icons?:{resume?,open?} (HTML string or Element), titles?:{resume?,open?}}
function termSplitSet(split, s)  // s={resumable:bool, here?:bool (default true), ext:bool}. The ONLY label/visibility API.
function termSplitOn(split, h)   // h={resume(e), open(e), external(e)}. Binds the 2 primaries + 2 items; idempotent (_ts.on)
function termSplitOpen(split, where)  // where="first"|"last"|null
function termSplitClose(except)       // closes every open registry split except `except` (keeps today's name and callers)
function termSplitSnapshot(prefix)    // -> {key, open, focus:"caret"|"primary:<act>"|"item:<act>"|null}|null
function termSplitRestore(snap)
function termSplitOnClick(e); function termSplitOnPointerDown(e); function termSplitOnKey(e); function termSplitOnFocusOut(e)
document.addEventListener("click",termSplitOnClick,true);
document.addEventListener("pointerdown",termSplitOnPointerDown,true);
document.addEventListener("keydown",termSplitOnKey,true);
document.addEventListener("focusout",termSplitOnFocusOut,true);
```

The modifier glyph is the **constant "⌥"** (O10). External launch is macOS-only (`osascript`) and loopback-only, so there is no "Alt" branch and no `termSplitAltName`.

**DOM that `termSplit(o)` builds.** The element id is `"tsplit-" + key.replace(/[^\w-]/g,"_") + "-menu"`. It registers `TSPLITS[key] = split`.

```html
<span class="tsplit" data-tsplit-key="KEY">
  <button type="button" class="PRIMARYCLS tsplit-primary" data-tsplit-act="resume">[span.tsplit-ico] Resume</button>
  <button type="button" class="PRIMARYCLS tsplit-primary" data-tsplit-act="open" hidden>[span.tsplit-ico] Open terminal</button>
  <button type="button" class="CARETCLS tsplit-caret" aria-haspopup="menu" aria-expanded="false"
          aria-controls="ID" aria-label="More Resume options" title="More Resume options">
    <span class="tsplit-solo-label">External</span><span aria-hidden="true">▾</span></button>
  <div class="tsplit-list" role="menu" id="ID" aria-label="Resume options" hidden>
    <button type="button" class="tsplit-item" role="menuitem" tabindex="-1" data-tsplit-act="open">Open terminal</button>
    <button type="button" class="tsplit-item" role="menuitem" tabindex="-1" data-tsplit-act="external" hidden>
      <span class="tsplit-label">Resume externally</span><span class="tsplit-arrow" aria-hidden="true"> ↗</span>
      <span class="tsplit-hint" aria-hidden="true">⌥-click</span></button>
  </div>
</span>
```

- Two real `<button>`s give two tab stops.
- Callers never pass item markup, so they cannot fork the item set, roles or style.
- `.tsplit` is always the root, even when nothing is in the menu, so one read-only rule covers every caller.
- `termSplit` binds the caret's own click listener (toggle). This is a per-button listener, so it works in `makeReal`.
- It ends with `termSplitSet(split, {resumable: !!o.resumable, ext: false})`.

**`termSplitSet(split, s)`.** This is the only place labels and visibility are decided (clause 8). Let `res = !!s.resumable`, `here = s.here !== false`, `ext = !!s.ext`.
- Visibility:
  - `res.hidden = !(here && res)`
  - `open.hidden = !(here && !res)`
  - `iOpen.hidden = !(here && res)`
  - `iExt.hidden = !ext`
- External label: `label.textContent = res ? "Resume externally" : "Open externally"`.
- External item title: `(res ? "Resume via claude --resume" : "Open a shell") + " in an external Terminal/iTerm window — this machine only"`.
- Primary titles are `titles.resume` / `titles.open`, plus `" — ⌥-click: " + (res ? "resume" : "open") + " externally"` **only when `ext`**. The shortcut is named only when it works.
- With no item visible: `caret.hidden = true` and the split closes.
- Caret `aria-label`/`title`: `"More " + (res ? "Resume" : "Open terminal") + " options"`. In solo mode (no primary visible): `"External terminal options"`.
- Classes:
  - `tsplit-solo` when no primary is visible. The caret then shows "External ▾", today's attached-toolbar behaviour.
  - `tsplit-nomenu` when the caret is hidden.
  - `split.hidden` when nothing is visible at all.

**State lives only in `caret[aria-expanded]` (O3+S2).** There is no `tsplit-open` class.
- `termSplitOpen(split, where)`:
  - closes the others;
  - sets `list.hidden = false` **first**;
  - runs `_tsplitFit(split)`;
  - sets `caret aria-expanded="true"`;
  - focuses the first or last visible item when `where` is given.
- `termSplitClose` reverses this: `list.hidden = true` and `aria-expanded="false"`.
- "Open" everywhere (CSS, Snapshot, Escape) means `caret.getAttribute("aria-expanded") === "true"`.

**`termSplitOn(split, h)`.** It adds one `click` listener to each of `res`, `open`, `iOpen` and `iExt`. Each listener:
- reads `act` from its button;
- **⌥-click (clause 6):** if `e && e.altKey`, the button is a primary, and `!iExt.hidden`, then `act = "external"`. If the external item is hidden, the modifier is ignored;
- for an item: `termSplitClose()` and then `caret.focus()` **before** the handler, so a dialog or overlay the action opens captures the caret as its opener;
- calls `e.preventDefault()` when it exists, then `h[act](e)` exactly once.

It never calls `stopPropagation`; a container that must ignore the click says so itself. There is no keyboard equivalent of ⌥-click (optional per clause 6); the menu item is the keyboard path.

**Pointer (document capture, real browsers).**
- `termSplitOnClick` **and** `termSplitOnPointerDown` (O8: iOS sends no document `click` for taps on inert areas): when the event's owner (`_tsplitOwner(e.target)`) is not an open split, call `termSplitClose()` with no focus move.
- Clicks inside a split are left to its per-button listeners.

**Keyboard (`termSplitOnKey`, capture; WAI-ARIA APG menu button).** Let `sp = _tsplitOwner(e.target)` and `isOpen = sp && caret aria-expanded === "true"`.
- On the caret:
  - `ArrowDown` opens and focuses the first visible item; `ArrowUp` opens and focuses the last. Both prevent and stop.
  - Enter and Space arrive as the button's native click, so the toggle opens and focuses the first item.
- With `isOpen` and the target in the list:
  - `ArrowDown`/`ArrowUp` move roving focus with wrap, skipping hidden items.
  - `Home`/`End` go to the first/last item.
  - All four prevent and stop.
- **`Escape` when `isOpen` and the target is the caret OR in the list (O4):** close, focus the caret, `preventDefault` + `stopPropagation`. The terminal overlay, board and page Escape listeners therefore do not also fire.
- `Tab`/`Shift+Tab` with the target in an open list: focus the caret, close, **no** `preventDefault`. The native Tab then moves on from the caret.
- `Escape` with no owning open split while some menu is open: close silently and let it through, so it never eats Escape typed into xterm or a dialog.
- Every other key falls through.

**`termSplitOnFocusOut`.** Close the owning split only when `e.relatedTarget` is a real element whose owner is a different split, or no split. A null `relatedTarget` never closes it: Safari does not focus a clicked button, and a node removed during a rebuild gives null. Outside presses are covered by click/pointerdown. This also makes board/detail `j`/`k` from inside a menu close it.

**`_tsplitFit(split)` (S5).** This is the single alignment rule.
- Called only from `termSplitOpen`, after the list is unhidden. It first removes `tsplit-start`.
- It walks `parentNode` to the nearest ancestor whose computed **`overflow-x`** is not `visible`, else the viewport.
- If the list's `getBoundingClientRect().left` is less than that box's left edge, it adds `tsplit-start`.
- It is guarded for missing `getBoundingClientRect`/`getComputedStyle`.
- Why: the toolbar shell (`ext_cr_term.css:43`) and the classic frame clip on the left. The board's `.cr-board-scroll` is `overflow-y:auto` only, so it is correctly ignored.

**Snapshot and restore (keep-open across a rebuild; classic 2 s poll + board poll).**
- `termSplitSnapshot(prefix)` scans `TSPLITS` keys starting with `prefix`, and returns the first split that is open or holds focus:
  - `open` is caret `aria-expanded`;
  - `focus` comes from comparing a guarded `document.activeElement` against `_ts.caret` / `_ts.res` / `_ts.open` / `_ts.iOpen` / `_ts.iExt`.
- `termSplitRestore(snap)` takes `TSPLITS[snap.key]`, which is the newly built node.
  - If it is missing, or not in the document (guarded `isConnected`), it does nothing. A changed session gives a changed key.
  - If `snap.open`, it calls `termSplitOpen(sp, null)`.
  - It then focuses the referenced button.

**CSS (`app.css`, replacing ~657-668).** It uses tokens only, CR first with classic fallbacks, and serves light, dark and both UIs.

```css
/* Split button (termSplit in app.js): primary + joined menu button. One block for every caller. */
.tsplit{display:inline-flex;flex-wrap:nowrap;align-items:stretch;gap:0;position:relative;white-space:nowrap}
.tsplit[hidden],.tsplit-list[hidden],.tsplit [hidden]{display:none!important}
.tsplit>button.tsplit-primary,.tsplit>button.tsplit-caret{align-self:stretch}
.tsplit:not(.tsplit-solo):not(.tsplit-nomenu)>.tsplit-primary{border-top-right-radius:0;border-bottom-right-radius:0;border-right-width:0}
.tsplit:not(.tsplit-solo):not(.tsplit-nomenu)>.tsplit-caret{border-top-left-radius:0;border-bottom-left-radius:0;
  border-left:1px solid color-mix(in srgb,currentColor 35%,transparent);padding-left:6px;padding-right:6px;min-width:24px}
.tsplit-caret{cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:4px}
.tsplit-solo-label{display:none}.tsplit-solo .tsplit-solo-label{display:inline}
.tsplit-list{position:absolute;top:100%;right:0;left:auto;margin-top:4px;z-index:80;display:flex;flex-direction:column;
  align-items:stretch;gap:2px;min-width:100%;padding:4px;background:var(--surface-raised,var(--raised));
  border:1px solid var(--line-subtle,var(--line3));border-radius:8px;box-shadow:var(--shadow-overlay,0 6px 18px rgba(0,0,0,.25))}
.tsplit.tsplit-start .tsplit-list{left:0;right:auto}
.tsplit-item{display:flex;align-items:center;gap:12px;width:100%;padding:6px 10px;border:0;border-radius:6px;background:none;
  color:var(--text-primary,var(--text));font:inherit;font-size:12px;text-align:left;white-space:nowrap;cursor:pointer}
.tsplit-item:hover,.tsplit-item:focus-visible{background:var(--fill-row-hover,var(--selbg))}
.tsplit-item:focus-visible{outline:2px solid var(--line-focus,var(--ring1));outline-offset:-2px}
.tsplit-hint{margin-left:auto;color:var(--text-muted,var(--muted));font-size:11px}
html.tracker-readonly .tsplit{display:none!important}
```

- The joined-shape rules are (0,4,0)/(0,5,0). They beat every caller's button rules, including the header's responsive `.cr .crd-row1-actions .crd-btn` (0,3,0, later in source; S4).
- `align-self:stretch` (0,2,1) beats `.tracker-next .cr-tile-action{align-self:flex-start}` (0,2,0), so both halves stay one height (O5).
- `border-right-width:0` removes the classic `.mini` 2px seam (O6).
- The divider is `currentColor`-derived, so it is visible on solid fills and the `.mini` chip in both themes. The caret takes the **same variant class as its primary**, which is the one caret style.
- **The read-only rule must be the block's LAST line, directly before the existing `html.tracker-readonly .ren,...` rule (~670).** `test_cr_readonly_ui` `test_readonly_css_only_under_class` requires every app.css rule after the first `html.tracker-readonly` to be read-only-scoped.
- Same unit:
  - delete the legacy `.tsplit-menu`/`summary`/`::-webkit-details-marker`/`.tsplit-list #extnative` rules;
  - delete `html.tracker-readonly .tracker-next .crd-row1-actions .tsplit,` from `ext_cr.css`;
  - in `tests/test_icons.py` ~221, change `set("⌘")` to `set("⌘⌥")` and add "and the Option-key glyph in the split button's ⌥-click hint" to its comment (O2).

**Unit 1 tests.**
- `tests/_tsplit_dom.py`: take the existing `_FAKE_DOM` + `_extract` + `_run` from `tests/test_term_split_menu.py:57-124` (O10: no fifth fake DOM) and extend it with:
  - `document.createElement`, `setAttribute` / `getAttribute` / `hasAttribute` / `removeAttribute`, `textContent`, an `innerHTML` store, `appendChild`, `contains`, `isConnected`;
  - `focus()` that sets `document.activeElement`;
  - per-element listeners, and `dispatch(el, type, init)` that runs the document capture listeners and then bubbles;
  - a `getBoundingClientRect` that can be set per element, a `getComputedStyle` stub, and `location`/`navigator`/`fetch` stubs.
  - `helpers_js()` extracts every Unit 1 function and prepends `const TERM_EXT={allowed:null,probe:null}; const TSPLITS={}; var sessions=[];`. Unit 6 later makes `test_term_split_menu.py` import from here and deletes its copy.
- `tests/test_tsplit_shared.py` cases:
  1. **Markup/ARIA:**
     - two `button[type=button]` primaries;
     - caret `aria-haspopup="menu"` / `aria-expanded="false"` / `aria-controls` equal to the list id / an `aria-label` naming the primary;
     - a `role=menu` list, hidden;
     - items `role=menuitem tabindex=-1`;
     - the hint and arrow `aria-hidden`;
     - the root is always `.tsplit`;
     - `TSPLITS[key]` is the node.
  2. **`termSplitSet` truth table** over resumable × here × ext: labels, hidden flags, `tsplit-solo`/`tsplit-nomenu`/`split.hidden`, and the "⌥-click" title present only when ext.
  3. **Caret click:** opens, `aria-expanded="true"`, focuses the first visible item. A second click closes. Opening A closes B.
  4. **Keys:**
     - ArrowDown/ArrowUp on the caret;
     - roving with wrap, skipping hidden items; Home/End;
     - Escape from an item, **and Escape from the caret with the menu open**: closed, caret focused, stopped + prevented (a fake overlay bubble listener does not run);
     - Tab: caret focused, closed, **not** prevented;
     - Escape from a textarea with a stale open menu: closed, not prevented;
     - other keys untouched.
  5. **Item click:** closes, caret focused before the handler runs, the handler called exactly once. A second `termSplitOn` bind still fires once.
  6. **⌥-click:**
     - a primary with external visible runs `external`;
     - with external hidden it runs the primary;
     - the Open item with ⌥ runs `open`;
     - an event object without `altKey`/`preventDefault` does not throw.
  7. **Outside close:** `pointerdown` and `click` outside close. Inside does not.
  8. **focusout:** an outside `relatedTarget` closes; a null one does not.
  9. **Snapshot/restore:**
     - open + item focus restored onto a rebuilt node with the same key;
     - caret focus with the menu closed restored;
     - a different key does nothing.
  10. **`_tsplitFit`:** the list is unhidden before measuring. A nonzero rect crossing an `overflow-x:hidden` parent adds `tsplit-start`. An `overflow-y:auto`-only parent does not.
  11. **`trackerIsLocal`:** true only for `localhost` and `127.0.0.1`. False for `localhost.evil.com`, `127.0.0.1.nip.io`, `t1.localhost` and `example.com`.
  12. **`termExtAllowed`:** remote gives false with 0 fetches. Local gives null and then exactly 1 POST across many calls. 403 gives false, 400 gives true, a rejected fetch gives false. `termExtDeny` latches false.
  13. **`termResumable`:** the row flag wins both ways; the id rule applies with no row; null/"" gives false.
  14. **`makeReal` smoke (S3):** under the real `_REAL_DOM_PREAMBLE`, `termSplit` + `termSplitSet` + `termSplitOn` + `termSplitSnapshot`/`Restore` do not throw, and `simulateClick` on the Resume primary calls `h.resume` once.
  15. **CSS source checks:**
      - `.tsplit-list` has `z-index:80` and `right:0`;
      - the read-only rule is the last split rule, immediately before `html.tracker-readonly .ren`;
      - `.tsplit-list[hidden]` hides;
      - no `details`/`summary`/`.tsplit-menu` remains in `web/`;
      - no hex literal is in the block, and the divider uses `currentColor`;
      - no state class other than `tsplit-solo`/`tsplit-nomenu`/`tsplit-start` is named in any `web/*.css` file;
      - no web/*.css file other than app.css has a selector whose last compound targets `.tsplit-list`, `.tsplit-item` or `.tsplit-caret` (ignoring `:not(...)`). The **one sanctioned exception** is Unit 5's `.tracker-next .cr-tile-sidebar .tsplit-caret` padding rule.
  16. **Listeners:** the four are registered with capture `true`, and the window exports exist.
- **RED proof:** one targeted mutant per behaviour must turn its case red. The mutants are:
  - drop the `relatedTarget` check;
  - drop the wrap;
  - drop `stopPropagation` on Escape;
  - restrict Escape to list targets;
  - drop the ⌥ branch;
  - drop the probe cache;
  - drop the `^…$` exactness;
  - measure before unhiding;
  - drop the `pointerdown` listener;
  - make Set use `querySelector` (case 14 throws).

  Also revert test_icons.py and confirm `test_no_pictographic_emoji_outside_comments` goes red.

### P2. Units 2–5: per-caller (parallel after Unit 1; disjoint files)

| Caller | Resumability input | External handler | Read-only |
|---|---|---|---|
| E1 header | `termResumable(session.id \|\| sid)` (the namespaced id, as base) | `session:openExternal {id}` (boot) | app.css universal rule |
| E2 toolbar | `termResumable(st.sessionId)` via `isClaudeId` | `_openExternal(isClaudeId(st.sessionId) ? "resume" : "cwd")` | app.css universal rule |
| E3 classic | `termResumable(cur)` via `isClaudeId` | `openTerm(resumable ? "resume" : "cwd")` | app.css universal rule |
| E4 board hero | `!!s.resumable`, the server flag on the row it already has | `session:openExternal {id}` (boot) | existing `ctx.readOnly()` skip + app.css rule |

**Unit 2: header + boot.**

Files (exclusive): `aitracker/web/ext_cr_detail.js`, `aitracker/web/ext_cr_detail.css`, `aitracker/web/ext_cr_boot.js`, and new `tests/test_tsplit_header.py`.
- **`SKELETON`.** Replace the module-load `termSplit(...)` string call (~1380-1388) with `'<span class="crd-split-slot"></span>'`.
- **New `function mountHeaderSplit(node, ctx, ui)`.** Call it in `Detail.prototype.mount` right after `ui` is created. It does three things:
  - Builds `var s = termSplit({key: "crd-head", primaryCls: "crd-btn crd-btn-solid", caretCls: "crd-btn crd-btn-solid", resumable: true});`.
  - Mounts it with `qs(node, ".crd-split-slot").appendChild(s)`. That `qs` runs on the detail DOM once, before any helper call.
  - Wires it with `termSplitOn(s, {resume: function () { var sid = ui.sid; if (sid) ctx.emit("session:resume", { id: sid }); }, open: function () { var sid = ui.sid; if (sid) ctx.emit("terminal:open", { id: sid }); }, external: function () { var sid = ui.sid; if (sid) ctx.emit("session:openExternal", { id: sid }); }});`.
  - Keep `node._crSplit = s` for `syncHeaderSplit`.
  - Keep the literal `ctx.emit("session:resume", { id: sid });`. `test_cr_board_resume_button` pins it.
- **Delete the now-unreachable cases** `"open-terminal"`, `"resume"` and `"external"` from the delegated `node` click switch (~1918-1935), and move their comments into `mountHeaderSplit`.
- **New `function syncHeaderSplit(node, sid)`.** In `renderHeader`, it replaces everything from `var isLocalhost = ...` through `termSplitSync(qs(node, ".tsplit"));` (~2551-2560), and is called as `syncHeaderSplit(node, String(session.id || sid || ""))` (O9: the namespaced id, as base). Its body:
  - `var split = node._crSplit; if (!split) return;`
  - `split.setAttribute("data-sid", sid);`
  - `var ext = termExtAllowed();`
  - `termSplitSet(split, {resumable: termResumable(sid), ext: ext === true});`
  - `if (ext === null) termExtProbe().then(function () { if (split.getAttribute("data-sid") === sid) termSplitSet(split, {resumable: termResumable(sid), ext: termExtAllowed() === true}); });`
- **Comment reference.** The `isLocalhost` comment reference near ~2471 now points at `trackerIsLocal` in app.js.
- **`ext_cr_detail.css`.** Delete the four tsplit overrides (~462-468), and add `.cr .crd-split-slot{display:contents}`. The `.crd-btn-bare:not(.tsplit-item)` band rule stays unchanged.
- **`ext_cr_boot.js` `on('session:openExternal')`.**
  - `var resumable = termResumable(id);` replaces the regex.
  - On `res.status === 403`, in both the first attempt and the recreate retry, call `termExtDeny()` before the notify.
  - Fix the stale "mirrors ext_launch.js's isClaudeId" comment.
- **Tests (`test_tsplit_header.py`, `_tsplit_dom.py`).** Extract `mountHeaderSplit` and `syncHeaderSplit`, with stub `qs`/`ctx`/`ui`.
  - (a) Claude id: Resume primary, Open item, "Resume externally".
  - (b) `auggie:x`: Open terminal primary, no Open item, "Open externally".
  - (c) `sessions=[{id:"bare", resumable:false}]` makes `bare` non-resumable.
  - (d) Host checks:
    - `localhost.evil.com`: external hidden and 0 fetches;
    - `localhost` + 403: external hidden;
    - `localhost` + 400: shown after the probe `.then`, with no second `renderHeader`.
  - (e) Event checks:
    - the external item emits `session:openExternal {id}`;
    - ⌥-click Resume emits `session:openExternal`, not `session:resume`;
    - a plain click emits `session:resume` once.
  - (f) **Comment-stripped** `renderHeader` source has no `isLocalhost` and no `location.hostname` (O9).
  - (g) The boot `session:openExternal` slice contains `termResumable(` and `termExtDeny(`.
  - **RED mutant:** put the old unanchored regex back in place of `termExtAllowed()`. (d) and (f) go red.

**Unit 3: in-terminal toolbar.**

Files (exclusive): `aitracker/web/ext_cr_term.js`, `aitracker/web/ext_cr_term.css`, and new `tests/test_tsplit_toolbar.py`.
- **`_build`.** The bar keeps an empty `<div class="cr-term-group" data-group="primary"></div>`. Delete the `termSplit(...)` string and the `open-here`/`resume-here`/`ext-terminal`/`ext-resume` buttons.
- **Mount after `bar.innerHTML = ...`, before `_wireStaticHandlers`.** The split's buttons have no `data-action`, so nothing is double-wired.
  - Build: `var ts = termSplit({key: "cr-term", primaryCls: "cr-term-btn cr-term-btn-solid", caretCls: "cr-term-btn cr-term-btn-solid", resumable: false, titles: {resume: "Resume this session in a terminal right here (claude --resume)", open: "Open a terminal right here, cd'd to this session's folder"}});`
  - Attach: `bar.querySelector('[data-group="primary"]').appendChild(ts);`
  - Wire: `termSplitOn(ts, {resume: function () { _openInline(st.sessionId, "resume"); }, open: function () { _openInline(st.sessionId, "cwd"); }, external: function () { _openExternal(isClaudeId(st.sessionId) ? "resume" : "cwd"); }});`
- **Remove the old wiring.**
  - `el`: keep `split: ts`; delete `splitList`, `openHere`, `resumeHere`, `extTerminal` and `extResume`.
  - Delete the matching `_onAction` cases.
  - Delete `extAllowed`, `extProbing` and `_probeExternal`.
  - `_openExternal`'s 403 branch: `termExtDeny(); _syncControlVisibility();`.
- **Thin wrappers.** `localOnly()` becomes `return trackerIsLocal();` and `isClaudeId(sid)` becomes `return termResumable(sid);`. The names stay for `_loadHeaderInfo` and the other tests.
- **`_syncControlVisibility()`.** `var ext = termExtAllowed(); _syncSplit(ext === true); if (ext === null) termExtProbe().then(_syncControlVisibility);`. The probe resolves once, so this terminates. Before the probe answers, external is hidden; the base showed it optimistically.
- **`_syncSplit(ext)`.** Delete `_placeOpenHere`. Keep the `_syncSplit` name, since `_syncStatusBar` calls it. Body: `if (!el.split) return; termSplitSet(el.split, {resumable: isClaudeId(st.sessionId), here: !st.attached, ext: ext === undefined ? termExtAllowed() === true : ext});`.
- **`ext_cr_term.css`.** Delete the two `.cr .cr-term-controlbar .tsplit-list` lines (~168-171).
- **Tests (`test_tsplit_toolbar.py`).**
  - (a) Attached Claude: both primaries and the Open item are hidden; external is visible; solo; caret visible.
  - (b) Unattached Claude: Resume, Open item, "Resume externally".
  - (c) `auggie:x`: Open terminal primary, "Open externally", and external gets `cwd`.
  - (d) Remote host: no external and 0 POSTs.
  - (e) A 403 from `_openExternal` hides external.
  - (f) In the source, `_placeOpenHere`, `ext-terminal`, `ext-resume` and `extAllowed` are absent, and `termSplitClose();` is still in `close()`.
  - (g) Escape with the caret focused and the menu open is stopped, so the overlay's bubble Escape listener (`ext_cr_term.js:249`) does not close the overlay. Escape from a fake xterm textarea with no open menu passes through.
  - **RED mutant:** ignore `here` in `_syncSplit`. (a) goes red.

**Unit 4: classic pane.**

Files (exclusive): `aitracker/web/ext_launch.js` and new `tests/test_tsplit_classic.py`.
- **Moved logic.** The ponytail exception comment above `localOnly()` shrinks to a one-line pointer to `trackerIsLocal()` in app.js. `localOnly()` becomes `return trackerIsLocal();` and `isClaudeId(sid)` becomes `return termResumable(sid);`.
- **Deleted state.** Delete `allowed`, `probing` and `probe()`. Keep `post()`.
- **`openTerm` 403 branch.** `termExtDeny(); if (lastD !== undefined) render(lastD);`. Add `let lastD;` and set `lastD = d` at the top of `render`. This replaces the `#extnative` surgery.
- **`render(d)`.** It keeps **snapshot/restore** (S6 was a false alarm: the whole pane, split included, is rebuilt every 2 s, and the base already carries state across it). Replace everything from `const openHtml` through the `onclick` wiring with:
  - `const resumable = isClaudeId(cur);`
  - `const snap = termSplitSnapshot("ext_launch:");`
  - `el.innerHTML = homeNote ? '<div class="extlaunchnote" data-el="homenote">' + esc(homeNote) + "</div>" : "";`
  - `const split = termSplit({key: "ext_launch:" + cur, primaryCls: "mini extlaunchbtn", caretCls: "mini extlaunchbtn", resumable, icons: {resume: ico("redo"), open: ico("play")}, titles: {resume: "Resume this session in a terminal right here in the browser (claude --resume)", open: "Open a terminal right here in the browser, cd'd to this session's working directory"}});`
  - `if (el.firstChild) el.insertBefore(split, el.firstChild); else el.appendChild(split);`
  - `const ext = termExtAllowed();`
  - `termSplitSet(split, {resumable, ext: ext === true});`
  - `if (ext === null) termExtProbe().then(() => render(d));`
  - `termSplitOn(split, {resume: () => window.ExtVT ? window.ExtVT.open(cur, "resume") : alert("in-browser terminal unavailable"), open: () => window.ExtVT ? window.ExtVT.open(cur, "cwd") : alert("in-browser terminal unavailable"), external: () => openTerm(resumable ? "resume" : "cwd")});`
  - `termSplitRestore(snap);`
- **Removed ids and labels.** The ids `extvtopenbtn`, `extvtresumebtn`, `extopenbtn`, `extresumebtn` and `#extnative` go away. Labels unify to Resume / Open terminal + the one external item (D2).
- **Known gap, same as base:** a click whose mousedown and mouseup straddle a 2 s rebuild is lost. Document it in the PR.
- **Tests (`test_tsplit_classic.py`).** Run `ext_launch.js` via `new Function` with the real Unit 1 helpers and `_tsplit_dom.py`.
  - (a) An open menu + focus on the external item survive a re-render.
  - (b) Caret focus with the menu closed: after re-render the caret is focused and the menu stays closed.
  - (c) A changed `cur` is not restored.
  - (d) Host and probe checks:
    - remote host: no external and 0 POSTs;
    - local + 400: external present;
    - a 403 from `openTerm` makes the next render hide external.
  - (e) Non-Claude `cur`: Open terminal primary, "Open externally", and `openTerm("cwd")`.
  - (f) `termSplit` always yields a `.tsplit` root, so the read-only rule covers it.
  - **RED mutant:** turn `termSplitRestore(snap)` into a no-op. (a) and (b) go red.

**Unit 5: board hero tile.**

Files (exclusive): `aitracker/web/ext_cr_board.js`, `aitracker/web/ext_cr_board.css` and `tests/test_cr_board_resume_button.py`.
- **`sessionTile` hero sidebar.** Replace the `canResume ? Resume : readOnly ? null : Open terminal to answer` ternary with `readOnly ? null : heroSplit(s, canResume)`.
- **New local `heroSplit(s, canResume)`:**
  - Build: `var sp = termSplit({key: "board-hero:" + s.id, primaryCls: "cr-tile-action", caretCls: "cr-tile-action", resumable: canResume, icons: {resume: icon("play", '<path d="M8 4.5l11.5 7.5L8 19.5z"/>')}, titles: {resume: "Resume this session to answer", open: "Open a terminal to answer"}});`
  - Set: `var ext = termExtAllowed(); termSplitSet(sp, {resumable: canResume, ext: ext === true});`
  - Probe, re-setting the **same node** (O7+S7): `if (ext === null) termExtProbe().then(function () { termSplitSet(sp, {resumable: canResume, ext: termExtAllowed() === true}); });`
  - Wire: `termSplitOn(sp, {resume: function (e) { if (e && e.stopPropagation) e.stopPropagation(); ctx && ctx.emit && ctx.emit("session:resume", { id: s.id }); }, open: /* same shape, 'terminal:open' */, external: /* same shape, 'session:openExternal' */});`
  - `return sp;`
  - The hero is always awaiting (`tiles[0].hero` only when `state === 'awaiting'`), so `canResume === !!s.resumable && !readOnly`.
- **Non-hero tiles.** The non-hero icon-only `.cr-tile-resume` is unchanged (clause 5).
- **`tileBaseAttrs.onclick`.** The ignore selector becomes `'button,a,input,select,textarea,[role=button],[role=menu]'`.
- **`renderBoard`.** Before `els.board.innerHTML = ''`, take `var tsnap = termSplitSnapshot("board-hero:");`. Call `termSplitRestore(tsnap);` after the `focusedTileId` refocus block, so it wins.
- **`ext_cr_board.css` (scoped hero shrink, S1).** Do not widen the sidebar (O5's widening was rejected), and do not touch the shared `.tracker-next .cr-tile-action` rule (pinned at `test_cr_board_resume_button.py:204`).
  - `.tracker-next .cr-tile-sidebar .tsplit{max-width:100%;white-space:normal}`
  - `.tracker-next .cr-tile-sidebar .tsplit-primary{min-width:0;padding:7px 10px;text-align:left}`
  - `.tracker-next .cr-tile-sidebar .tsplit-caret{padding:7px 6px}`. This is the sanctioned exception in Unit 1's CSS check.
  - **No** `:has()` z-index rule by default. Unit 6's browser check adds `.tracker-next .cr-tile:has(.tsplit-caret[aria-expanded="true"]){position:relative;z-index:3}` to this file only if the list paints under the next tile.
- **Tests (expected change; edit this file's existing assertions).**
  - Hero markup:
    - the hero has a `.tsplit` with a Resume primary (icon + text);
    - its title starts with "Resume this session to answer", and names "⌥-click" when ext is allowed;
    - the caret has `aria-haspopup=menu`;
    - the items are Open terminal + "Resume externally".
  - Hero clicks:
    - `simulateClick` on the items emits `terminal:open` and `session:openExternal`;
    - Resume emits `session:resume` and stops propagation;
    - ⌥-click Resume emits `session:openExternal`.
  - Other tiles:
    - the Auggie hero has an Open terminal primary + "Open externally", replacing "Open terminal to answer";
    - non-hero is unchanged;
    - read-only gives 0 splits.
  - The probe 400 resolving makes external visible on the same node with no re-render (O7).
  - A click on `[role=menu]` does not activate the tile.
  - Snapshot/restore across `renderBoard` keeps the open menu and the focused item.
  - A CSS-source check confirms the three scoped sidebar rules (S1).
  - `test_no_hostname_gating_in_new_code` and `test_shared_tile_action_rule_does_not_force_nowrap` stay green.
  - **RED mutant:** drop `[role=menu]` from the ignore list. The tile-activation case goes red.

### P3. Unit 6: existing-test reconciliation, the full gate, end-to-end

Unit 6 runs after Units 2–5. It owns only test files that Units 1–5 do not touch, plus browser-check follow-ups. Its files:
- `tests/test_term_split_menu.py`
- `tests/test_cr_readonly_ui.py`
- `tests/test_term_vt_client.py`
- `tests/test_term_launch.py`
- `tests/test_cr_detail_action_row_responsive.py`
- `tests/test_page_bundle.py`
- `tests/test_term_vt_exec.py`, only if it fails
- `aitracker/web/ext_cr_board.css`, only for the conditional `:has()` rule

All of these are expected changes, made by editing the existing assertions:
- **`test_term_split_menu.py`:**
  - Import the fake DOM from `tests/_tsplit_dom.py` and delete the local copy.
  - Delete the `<details>`-era `TestTermSplitHelper`, `TestOverlaySplit`, `TestHeaderPrimarySwap`, `TestClassicPaneKeepsMenuOpenAcrossPoll` and `TestSplitCss`, plus `test_header_secondary_actions_only_inside_the_list`, `test_overlay_external_moved_into_the_list_and_group_removed` and `test_classic_native_buttons_only_via_the_split`. The Unit 1–5 files supersede them.
  - Keep `TestMountIntoEmptyListOnePost`, `TestResumeOpensOneEngineGuard`, `test_header_reset_closes_the_menu` (~375) and `TestStatusBarAttachedKeepsExternalReachable`. Re-point the last one at `termSplitSet`.
  - Keep `test_every_surface_calls_termsplit` and **add `ext_cr_board.js`** to it (O11).
  - Rewrite the docstring.
- **`test_cr_readonly_ui.py` ~176-180:** assert the app.css `html.tracker-readonly .tsplit` rule instead of the ext_cr.css header-scoped one.
- **`test_term_vt_client.py` ~270-290** and **`test_term_launch.py` ~575 and ~596-630:**
  - Replace the pins on "External terminal", "External resume", "Resume terminal here", `extopenbtn`, `if (localOnly())` and the `<button` count.
  - Assert instead:
    - `termSplit({` and `termExtAllowed()` in ext_launch.js;
    - "Resume externally" / "Open externally" in app.js;
    - `ico("redo")` / `ico("play")` passed as icons;
    - `localOnly` / `isClaudeId` delegating to `trackerIsLocal` / `termResumable`.
  - Keep the `function localOnly` order check (~112).
- **`test_cr_detail_action_row_responsive.py` ~103:** the labels now live in app.js. Assert "Resume", "Open terminal" and "Resume externally" there, and `termSplit(` in ext_cr_detail.js.
- **`test_page_bundle.py` `_HOME_NOTE_HARNESS`:**
  - Load the real Unit 1 helpers instead of the `(p, i) => p + i` string `termSplit`.
  - Give the fake `ext_launch` element `appendChild`, `insertBefore` and `firstChild`.
  - The note assertions are unchanged.
- **Must stay green:**
  - **every** module from `grep -l "_REAL_DOM_PREAMBLE\|_bundle_js" tests/*.py` (about 21, O1+S3);
  - every module from `grep -l "ext_cr_detail" tests/*.py` (the detail-mount set);
  - `test_icons.py`, `test_cr_routes.py` (hostname 300-char proximity: `trackerIsLocal` lives in the split block, far from `togglePin(`), `test_cr_tunnel.py`, `test_integration.py`, `test_cr_detail_agents_pill_and_markdown.py`, `test_cr_dialog_theme_and_close_label.py` and `test_page_css.py`.
- **Gate:**
  1. Run `unset TRACKER_AUTH;` first.
  2. Run one test module per process; never pipe it to `| tail`. A `Killed: 9` is OOM, not red.
  3. Run `node --check` on every edited JS file. A load-time throw silently kills every later module, and `make check` misses it.
  4. Run `make check`; it must print `selfcheck ok`.
  5. Commit once, after Unit 6 and the implementation review, with a Bash timeout over 6 min (the hook runs the full gate).
- **Rules for Units 1–6:**
  - Never commit, stash or `git checkout` a file.
  - A RED proof copies the file aside, applies the base (`git show HEAD:<path> > <path>`) or the one-line mutant, runs, and copies the file back.
- **End to end (/tracker-gap Step 4.4–4.5, /gap Step 5.1).**
  - Server:
    - restart a **worktree test server on a free port**;
    - never `pkill -f aitracker`; stop it by PID;
    - it is a UI change, so the page is only baked at startup.
  - `curl /` and grep for `function termSplit(o)`, `Resume externally`, `aria-haspopup` and `html.tracker-readonly .tsplit`.
  - Browser-check 4 entry points × light/dark × desktop/390px × `localhost` (external shown) / `127.0.0.1.nip.io` or the tunnel (external hidden, in-browser Resume shown). In each, check:
    - the keyboard path: Tab to the caret, ↓, ↑/↓, Esc returns to the caret, Esc on the caret inside the overlay keeps the overlay open, Tab closes;
    - ⌥-click;
    - an outside tap on touch emulation;
    - the toolbar/classic start-flip;
    - the hero split at 100% and 150% icon scale with no overflow;
    - the hero menu above the next tile (add the conditional `:has()` rule only if it fails);
    - **the caret hit box at 390px: flag anything under ~28px wide (not auto-fixed);**
    - focus order of the hero split versus the tile's own `tabindex`.

### P4. Sequencing

1. **Unit 1** lands first; every unit depends on its API and `_tsplit_dom.py`. It removes the legacy string `termSplit`, so the callers and `test_term_split_menu.py` are red until Units 2–6. That is acceptable because nothing commits before Unit 6. Each agent runs only its own modules plus `node --check`, and Unit 1 also runs the full `_REAL_DOM_PREAMBLE`/`_bundle_js` set.
2. **Units 2, 3, 4 and 5 run concurrently**, one agent each, on the disjoint file lists above. None of them edits app.js, app.css, ext_cr.css, test_icons.py, `_tsplit_dom.py` or another unit's file. An agent that needs a helper change stops and reports; it never forks a local copy.
3. **Unit 6** then reconciles the tests and runs the gate, the RED sweep and the end-to-end check.
4. Next come chain step 7, the `opus` adversarial review of the implementation, and step 8: `/branch-sync`, re-gate, then push `board-resume-parity` to `personal`.
5. **Clause 9:** hold `/tracker-push` until the other session's push to `personal/main` has landed, then run `/branch-sync` → gate → `/tracker-push`.

Suggested models (rule 3): Units 1–5 `sonnet`; Unit 6 `sonnet` for the edits, with a `haiku` gate-runner for the runs; the review `opus`.

### P5. Risky spots, each with its fallback

- **The bundle harnesses (`makeReal`) throw on query-based helpers.**
  - Primary fix: the harness-agnostic rules in P1 and shared case 14.
  - Fallback if a module still throws: add null-guards at the failing `_ts` access. Never widen `makeReal`, which 21 files share.
- **The classic 2 s rebuild and the board poll rebuild lose open state and focus.**
  - Primary fix: the registry-based snapshot/restore. The board restores after `focusedTileId`.
  - Fallback if flicker shows: reuse the split node when the key is unchanged, and only call `termSplitSet`.
- **The toolbar and classic menus sit at the far left inside `overflow:hidden`.**
  - Primary fix: `_tsplitFit`'s start-flip (unhide, then measure `overflow-x` frames).
  - Fallback: `o.align:"start"` for those two callers. That weakens clause 6, so it needs a user OK (D3).
- **xterm, the overlay's Escape and the focus trap.**
  - The capture handler acts only on targets owned by a split, plus the silent Escape close.
  - Escape on the caret or the list is stopped, so it never reaches the overlay's bubble listener.
  - `trapFocus` sees the caret after Tab, because the capture handler moves focus there first.
  - Fallback if the trap wraps: in the Tab branch, `preventDefault` and focus the next or previous `FOCUSABLE` after the split.
- **Board tile containers.**
  - `[role=menu]` is on the click-ignore list.
  - The tile's Enter handler checks `target === currentTarget`.
  - j/k close the menu via focusout.
  - Hero overflow is handled by the scoped shrink.
- **Safari and iOS.**
  - focusout ignores a null `relatedTarget`.
  - `pointerdown` handles outside taps.
- **Load-time throw.**
  - `SKELETON` no longer calls `termSplit` at load.
  - The helpers touch `document` only at call time.
  - `node --check` and `test_page_bundle` run.

### P6. What the plan deliberately changes or drops

- **Clause 4 consequence:** for a resumable session, the toolbar's and classic pane's plain **External terminal** (an external `cwd` shell) is gone; only **Resume externally ↗** remains. A non-resumable session gets **Open externally ↗**, an external `cwd` shell.
- **Clause 3 consequence:** "Open terminal here" and "Resume terminal here" become "Open terminal" and "Resume", with "right here (in the browser)" kept in the titles. The board Auggie hero's "Open terminal to answer" becomes "Open terminal", with that phrase as its title.
- **⌥-click** applies to whichever primary is shown (it runs "Open externally" on a non-resumable session). It is never the only path, and there is no keyboard equivalent.
- **Known gaps, same as base:**
  - a click straddling the classic 2 s rebuild is lost;
  - the caret's touch target is measured at 390px and flagged, not auto-fixed.
- **Clauses that cannot be met front-end-only:** none.

### P7. Decisions the user may want to overrule

- **D1:** drop the plain external shell for Claude sessions in the toolbar and classic pane (follows clause 4 "One"). The alternative is a second "Open externally ↗" item, for resumable sessions only.
- **D2:** unify the "…here" labels to "Resume" / "Open terminal" in all four places (clause 3 "same items everywhere").
- **D3:** end-aligned, with an automatic start-flip where the menu would be clipped. The alternative is strict end alignment.

## Review

Two independent adversarial reviews, run in parallel on different models:
- opus: [resume-split-button-review-opus.md](resume-split-button-review-opus.md) (O1–O11)
- sonnet: [resume-split-button-review-sonnet.md](resume-split-button-review-sonnet.md) (S1–S8)

## Reconciliation + clean plan (main thread, 2026-11-18)

Main-thread spot checks against the code:
- `tests/test_icons.py:210-222` has no ⌥.
- The fake DOM's `innerHTML` is a plain getter/setter that never parses (`tests/test_working_glow_board.py:245`).
- The hero sidebar is `flex:0 0 124px` (`ext_cr_board.css:1748`).
- The classic pane rebuilds the WHOLE pane, split included (`ext_launch.js:472`).

| # | Finding | Verdict | Folded in as |
|---|---|---|---|
| O1 + S3 | Bundle-harness fake DOM (`makeReal`: no parsing `innerHTML`, `closest`→null, no `contains`/`activeElement`, one listener per type) would make the new helpers throw and turn ~18–21 modules red | **confirmed (both)** | Build with `createElement` only. Keep element refs on `split._ts`. Set/On/Open/Close/Snapshot/Restore never run selector queries. Listeners tolerate a missing `target`/`preventDefault`/`altKey`. Guard `document.activeElement`/`contains`. Unit 1 and Unit 6 run EVERY module from `grep -l "_REAL_DOM_PREAMBLE\|_bundle_js" tests/*.py` plus the detail-mount modules. |
| O2 | "⌥" (U+2325) isn't whitelisted, so `test_icons` goes red | **confirmed** | Unit 1: `set("⌘")` → `set("⌘⌥")` in `tests/test_icons.py:221`, with its comment. |
| O3 + S2 | `.tsplit-open` used by board CSS but never set | **confirmed (both)**; opus's fix (add a class) **overengineered** | No new state class. Key all CSS on `.tsplit-caret[aria-expanded="true"]`, the state that already exists (sonnet's way). Keep the board `:has()` z-index rule only if the browser check shows the list painting under the next tile. |
| O4 | Escape on the focused caret while the menu is open falls through and closes the terminal overlay | **confirmed** | The Escape branch covers caret and list whenever the caret's `aria-expanded` is true: close, `stopPropagation`, focus caret. Shared test case. |
| O5 + S1 | Hero split overflows the ~107px usable sidebar; `.cr-tile-action{align-self:flex-start}` breaks equal height | **confirmed (both)**; opus's "widen the sidebar" **rejected** (changes tile layout) | Sonnet's scoped shrink: `.tracker-next .cr-tile-sidebar .tsplit{max-width:100%}`, primary `min-width:0;padding:7px 10px`, caret `padding:7px 6px`, without touching the shared `.cr-tile-action` rule (pinned by `test_cr_board_resume_button.py:204`). Plus opus's `align-self:stretch` on both split buttons in app.css. CSS-source test plus a browser check at 100%/150% icon scale. |
| O6 | Classic `.mini` border + divider gives a 2px seam | **confirmed (minor)** | `border-right-width:0` on the joined primary. |
| O7 + S7 | Hero external item missing until the next poll (probe unresolved on first render) | **confirmed (both)** | `heroSplit`: when `termExtAllowed()===null`, `termExtProbe().then(()=>termSplitSet(sameNode,…))`. Board test. |
| O8 | Outside tap doesn't close the menu on iOS (no document click) | **confirmed, same as base**; fix is one listener, kept | Outside-close also on a `pointerdown` capture listener. Shared test case. |
| O9 | Detail test (f) trips on a comment; header must pass `session.id‖sid` (namespaced) | **confirmed** | As written by opus. |
| O10 | `termSplitAltName` "Alt" branch is dead (external launch is macOS-only); a fifth fake DOM | **confirmed: cut** | Constant "⌥"; build the shared test DOM from the existing `_FAKE_DOM`/`_helpers_js` in `test_term_split_menu.py`. |
| O11 | Test accounting: board missing from `test_every_surface_calls_termsplit`; read-only rule must stay last before the first `html.tracker-readonly` rule (`test_cr_readonly_ui`); "fails on base" claims vacuous | **confirmed** | Board added. Read-only CSS placement pinned. One mutant RED proof per unit (header back to the regex, `here` ignored, no-op restore, `[role=menu]` guard dropped). |
| S4 | Header responsive rules (0,3,0, later in source) override caret padding | **confirmed (cosmetic)**; kept for contract clause 6 (one style) | Raise the caret rule to `.tsplit:not(.tsplit-solo):not(.tsplit-nomenu)>.tsplit-caret`. |
| S5 | `_tsplitFit` measures a still-hidden list (0×0) and the board flips against the scroll box | **confirmed** | Unhide before measuring; measure only `overflow-x` clipping frames. |
| S6 | "Classic only rebuilds the home note", so reuse the node instead of snapshot/restore | **false alarm**: the premise is wrong; `ext_launch.js:472` rebuilds the split every 2 s | Keep snapshot/restore (already needed for the board; the base already does this for classic). A click lost mid-rebuild is a known gap, same as base. |
| S8 | List notes | informational | none |

**Missed by both / not examined:** caret touch-target size (NN/g: ≥1 cm on touch) was not checked; the browser check at 390px measures the caret's hit box, and anything under ~28px wide is flagged, not auto-fixed. Neither review examined keyboard focus order inside the board tile's split relative to the tile's own `tabindex`; the browser check covers it.

**Clean plan = `## Plan` (P0–P7) + every "Folded in as" cell above.** Where they conflict, this table wins.

### Re-review amendments (opus re-review of the revised plan, 2026-11-18): all confirmed, binding

The re-review found every row applied and the Units 2–5 file sets disjoint. Its verdict was "BLOCKED: R1", and it said that one-line sequencing edit makes the plan ready. Applied here, with no further planner round:

- **R1 (major, process):** Unit 1 does NOT run the full bundle set. While the header, toolbar and classic still call the old `termSplit(string)`, every `_bundle_js` module throws at load.
  - Unit 1 runs only `test_tsplit_shared` (case 14 extracts the helpers into `_REAL_DOM_PREAMBLE`, not `_bundle_js`), `test_icons`, and `node --check` on its files.
  - Units 2–5 run only their extract-based modules plus `node --check`.
  - Unit 5's bundle-based `test_cr_board_resume_button` counts only after Units 2–4 report done.
  - **Unit 6 alone runs every module.**
  - No legacy-signature shim.
- **R2 (test):** Unit 5 opens the menu with `caret._listeners.click({target: caret})`, not `simulateClick`, and picks buttons by `_attrs['data-tsplit-act']` and `!hidden`. The shared listener is unchanged.
- **R3 (test):** Restore and Snapshot skip only when `sp.isConnected === false`. The Unit 5 restore case asserts open state only (`aria-expanded="true"`, `list.hidden===false`), and goes red if `termSplitRestore` is deleted. Focus is covered by shared case 9 and classic (a).
- **R4 (rationale):** `.cr-board-scroll` IS measured (computed `overflow-x:auto`), and that is correct. Drop the "correctly ignored" sentence. Case 10's sub-case becomes "a parent whose computed `overflowX` is `auto` flips when crossed".

## Implementation log

| Unit | Agent | Status |
|---|---|---|
| 1 shared helper + CSS + shared test DOM | sonnet | done: app.js termSplit family + app.css block + ext_cr.css rule + test_icons + _tsplit_dom + test_tsplit_shared (15d/15e wait on Units 2-5) |
| 2 header | sonnet | done: mountHeaderSplit/syncHeaderSplit + boot termResumable/termExtDeny + test_tsplit_header |
| 3 toolbar | sonnet | done: toolbar split mounted via termSplit, old wiring removed, test_tsplit_toolbar green |
| 4 classic | sonnet | done: ext_launch.js on termSplit + snapshot/restore, tests/test_tsplit_classic.py (10 green, RED proven) |
| 5 board hero | sonnet | done: heroSplit + snapshot/restore + [role=menu] guard + scoped CSS; 21 board tests green |
| 6 old tests + full gate + RED proofs | sonnet / haiku gate | done: 6 old test modules reconciled (readonly_ui, page_bundle, term_launch, term_split_menu on _tsplit_dom, cr_detail_action_row_responsive, term_vt_client), README updated; gate 172/172 modules rc 0/5 after fixes (2 load-sensitive term_vt tests failed in the full run, pass isolated); no source edits; RED sweep and :has() z-index browser check NOT done |
| code review | opus + sonnet | pending |
| review fixes | sonnet | done: A1+S3 prune (_tsplitPrune), A2 list label, A3+S2 termExtDeny re-sync via t.s, S1 hint hidden in solo (app.js; 4 tests in test_tsplit_shared, RED proven); B1 hero CSS ellipsis + caret flex:none (ext_cr_board.css, test_cr_board_resume_button RED proven); B2 README; B3 dead localOnly removed + comments + test_term_vt_client anchor |

## Code review reconciliation (main thread, 2026-11-18)

Reviews:
- opus A (helpers, header, toolbar): [codereview-opus-a](resume-split-button-codereview-opus-a.md). Verdict SHIP; 16 mutants all RED.
- opus B (classic, board, CSS, README): [codereview-opus-b](resume-split-button-codereview-opus-b.md). Verdict FIX FIRST 1; 8 mutants all RED; the board `closest()` patch exercises the real selector.
- sonnet (4-place contract parity): [codereview-sonnet](resume-split-button-codereview-sonnet.md). Verdict SHIP.
- Browser check on port 8797: [browser](resume-split-button-browser.md). Board, header, classic, light/dark and console all PASS. The hero menu paints above its neighbour, so the `:has()` z-index rule is NOT needed. The toolbar was not testable without starting a process.

| # | Finding | Verdict | Action |
|---|---|---|---|
| A1 + S3 | `TSPLITS` registry never prunes detached splits (`app.js:142`) | **confirmed (both)** | Prune entries whose node `isConnected === false` when a split registers and in the outside handler. Test: registry size stays bounded across re-renders. |
| A2 | Menu `aria-label` is always "Resume options" (`app.js:190`), even when the primary is Open terminal | **confirmed** | `termSplitSet` sets the menu's label from the current primary ("Resume options" / "Open terminal options"), and the caret's name to match ("More Resume options" / "More Open terminal options"). Test in test_tsplit_shared. |
| A3 + S2 | After a 403, the header's and board's external item stays visible until the next render (`ext_cr_boot.js:803,807`) | **confirmed (both)** | After `termExtDeny()`, re-sync every live split from the registry: one `termExtDeny` that calls `termSplitSet` on registered connected splits, so no per-caller wiring is needed. Test: 403 → external hidden at once in header and board. |
| S1 | "⌥-click" hint shows in the toolbar's attached solo mode, where no primary exists | **confirmed** | `termSplitSet` hides the ⌥ hint when the primary is hidden or not resumable. Test in test_tsplit_shared / toolbar. |
| B1 | Hero Resume label may spill into the caret at icon scale ≥140% (estimated, not measured) | **plausible: fix accepted**, since it is cheap and scoped | Scoped to `ext_cr_board.css` `.cr-tile-sidebar .tsplit-primary`: `min-width:0; overflow:hidden; text-overflow:ellipsis`. The caret never shrinks (`flex:none`). Browser re-check at 150% icon scale. |
| B2 | README L202 / L120 out of date | **confirmed** | Update both to the shipped behaviour. |
| B3 | Stale comments and a dead `localOnly()` in `ext_launch.js` | **confirmed** | Delete the dead function and fix the comments. |
| B4 | Probe re-renders a stale `d` in classic | **same as base**: no change | Known gap; documented here. |
| B5 | A click lost mid-rebuild also applies to the board | **same as base**: no change | Known gap; documented here (as S6). |
| S4 | Board reads raw `s.resumable` rather than `termResumable` | **no change**: same value (`termResumable` reads that flag first); the board's gate is `awaiting && resumable` | none |
| Browser | Caret hit box is 24px (< 28px touch threshold) | **parked: the user's call** (a design size; the dashboard is mostly desktop) | Options: keep 24px / raise to 28px. Recommendation: 28px on coarse pointers only (`@media (pointer:coarse)`). |
| Browser | Caret tooltip doesn't name ⌥ (the primary's tooltip and the menu item do) | **no change**: contract clause 6 says "named in the tooltip and beside the menu item"; both are met | none |
| Missed | Toolbar split never seen in a real browser | open | The browser re-check opens the toolbar only if a terminal is already running; otherwise it is named as unverified in the final report. |
