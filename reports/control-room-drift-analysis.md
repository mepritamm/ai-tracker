# Control Room — drift analysis against the 2026-08-30 handoff bundle

Date: 2026-08-31
Bundle audited: `~/Downloads/app-ui-redesign-request 2/` (extracted 2026-08-30 04:58)
Code audited: `worktree-cr-drift` @ `aadcae5`
Method: six independent agents, one per spec doc + one precedence check. Per-doc tables in `reports/drift/`.

---

## 0. The precedence question — settled

The bundle README says *"Where the prototype and this documentation disagree, this documentation wins."*
`reports/control-room-redesign.md:180-191` records the opposite owner ruling: *"go by the HTML. Round 5 is the latest and wins."*

An older copy of the bundle exists on disk at `~/Downloads/design_handoff_control_room/` (the `v2` zip, 2026-08-29).
`diff -q` against the current bundle:

- **Byte-identical**: `02-shell-and-board.md`, `03-detail-view.md`, `04-coverage-and-help.md`, `05-terminal-and-dialogs.md`, `PROMPTS.md`, `README.md`
- **Differ**: `01-foundations.md` and `AI Tracker Redesign.dc.html`
- Within the `.dc.html`, the **Round 5 artboards (`id="5a"`–`"5d"`) are byte-identical**; every change is in the historical Round 1–3 artboards.

**The only hunk in `01-foundations.md`** (old lines 99–165) rewrites the Dark theme section, adding *"The mistake to avoid — this one shipped once and had to be fixed"*, a 3-rule recipe, and a measured-contrast table. That text post-dates this repo's own commit `5ffeabf` ("dark theme actually applies") — the doc was updated **after** seeing the shipped bug.

### Consequences

1. **Dark theme is the one place this bundle genuinely supersedes the code.** Treat `01-foundations.md`'s Dark section as authoritative.
2. **Everywhere else, nothing new overrides the owner's HTML-wins ruling.** Findings justified in-code as "prototype wins" are standing decisions, not drift. Do not revert them.
3. **Two owner asks have no source in this bundle at all** — the rail directory + grouping control, and any "3–8" slider bounds. They were verbal and never reached a re-export. The bundle cannot authorize them either way.

---

## A. Confirmed drift — fix, no ruling needed

| # | Finding | File:line | Sev | Confirmed by |
|---|---|---|---|---|
| A1 | Dark `--surface-agent-quiet/awaiting/failed` set to ink-only hex `#52400F`/`#6E3711`/`#642113` — the exact values the new Dark section forbids as fills. Correct: `#322A16`/`#3A2A18`/`#3A211A`. `--surface-agent-active` gradient start same bug | `ext_cr.css:296-299` | HIGH | 01 |
| A2 | Whole dark `--surface-*` block (15 tokens) deviates from the "measured, do not regress" table; dark `--line-awaiting/done/flagged` hold unrelated **light**-theme values (wrong-column copy-paste) | `ext_cr.css` dark block | HIGH | 01 |
| A3 | Ungrouped agent sessions (`agent:true`, `group:""`) dropped from the board entirely. Code comment: *"Verified live: 950 sessions, 1 working, 0 tiles."* | `ext_cr_board.js:217-223` | HIGH | 02, 04 |
| A4 | Terminal-controls / model·effort·context mirror permanently hidden — gated on `session.term_attached`, a field **no provider or route ever sets** (zero hits in the Python tree). `GET /api/term/attached` exists unused at `term_vt.py:2650` | `ext_cr_detail.js:1751-1772` | HIGH | 03, 04 |
| A5 | Board never renders a **Failing** tile state; rank logic *"never includes a 'failing' key"* though the doc lists it as one of six. Word is generic `"Failing"` vs doc's `"fail: <command>"` | `ext_cr_board.js:46-48` | HIGH | 01 |
| A6 | Config **Port/Host are editable fields POSTing to `/api/config`**; doc 04 specifies read-only display. An unsanctioned write surface | `ext_cr_dialogs.js:1129-1136` | MED | 05, 04 |
| A7 | Terminal overlay has `role="dialog"` + Esc/backdrop but **no focus trap and no focus restore**, unlike every `CR.dialogs` dialog | `ext_cr_term.js` overlay | MED | 05 |
| A8 | Board scroll container has no scroll-preservation across re-renders — on a 2s poll it fights the user. Doc 02 calls this *"the single most likely regression"* | `ext_cr_board.js` render | MED | 02 |
| A9 | Back-line "N of M needing attention · j/k" hint is dead — `state.triage` is never passed | `ext_cr_boot.js:903` → `ext_cr_detail.js:1292-1304` | MED | 03 |
| A10 | `session.pinned` absent from the per-session detail dict → header Pinned pill can never render | detail dict seam | MED | 03 |
| A11 | Flag badge shows a count but no flag **text** — the data isn't in the session-list shape | `registry.py` | MED | 04 |
| A12 | #41 missing "status not recorded" string; #43 PR panel never shows a title; #10 search doesn't rank name-matches first | detail/board | LOW–MED | 04 |

---

## B. Standing owner decisions — do NOT "fix"

Docs 02/03 and the Round 5 HTML are unchanged since the ruling, so these remain correct as shipped:

- Emoji tint recipe (`grayscale/sepia` construction) — `01-foundations.md:275` "(decision 4, revised)" is **identical in both bundle copies**, so the revision predates the ruling
- Working-tile border/glow restricted to `s.bg>0`
- "project · tool" sub-line on hero tile only
- Triage counts at 31px rather than 33px
- Separate `ext_cr*` files instead of appending to `app.css`/`app.js` (`page.py:8-10` already globs `ext_*`; zero server change)

Reverting any of these would re-introduce a state the owner explicitly rejected.

---

## C. Needs an owner decision — do not guess

| # | Question | Evidence |
|---|---|---|
| C1 | **Restore the 7-chip stat row?** (`files · commands · reads · commits · tests · tokens · branch` + `--`/`N/A` convention). Doc 04 lists it as capability #21 and doc 03 requires it; code deleted it, self-labelled *"design-audit drift 1"* / *"the ruling"*. The docs are unchanged since the ruling, so I cannot tell from the bundle whether the owner's ruling covered this specific row | `ext_cr_detail.js:637-646,1306-1327` |
| C2 | **Board-tile cap range.** Internal spec conflict: doc 02 says hard `slice(0,8)` "HARD CAP"; doc 04 specifies a slider **3–12**; shipped clamps **3–8**. The shipped value is a sensible reconciliation of the two docs — confirm before changing | `ext_cr_dialogs.js` config |
| C3 | **Rail directory + grouping control** — appears nowhere in this bundle. Build from the verbal ask, or drop? | no source |
| C4 | **Finish the phone layout?** Still missing back chevron + breadcrumb, 34px presence orb, 21px serif live narration, awaiting-question card | `ext_cr_detail.css` |

---

## D. Known deferred — leave as-is (server capability genuinely absent)

`cr:stop` and terminal model/effort switching (no server route; controls disabled with honest copy) · `cr:run-command` inline output pane (toast instead) · spine time-proportionality for Auggie/Augment-ext (`task_id` lives in a different id space than the task-storage uuid — no reliable join; degrades to equal-width) · todo counts/spine timings on historical sessions (Claude prunes its own task store; measured 18 of 35 dirs empty) · per-code-block copy buttons · mermaid diagram wiring.

---

## E. Contract status

| Clause | Verdict |
|---|---|
| Read-only toward sessions | Discharged — no write path into any session log; kill is `SIGKILL` on the process group |
| 2s poll + existing result shape, no new per-panel round-trips | Discharged — only pre-existing/action-triggered routes found |
| Provider-agnostic, honest degradation | Discharged |
| Gate stays green | Discharged at `aadcae5` (`env -u TRACKER_AUTH make check`) |
| Colour never carries meaning alone | **Now discharged** — independently audited this run (was *"believed discharged, NOT independently audited"*) |
| Lazy xterm.js load (~480KB, never at page load) | Discharged — `_loadXtermAssets()` reachable only via explicit Open/Resume click |

---

## F. Implementation plan

Sequenced so each phase is independently verifiable and the riskiest change lands with a live check behind it.

### P1 — Dark theme tokens (pure CSS, zero JS risk)
`aitracker/web/ext_cr.css`: replace the dark `--surface-*` block per the new Dark section's measured table (A1, A2); fix `--surface-agent-active` gradient start; re-point dark `--line-awaiting/done/flagged` at dark-ramp steps.
**Check**: load `.tracker-next.is-dark` in a browser and eyeball the six state surfaces. No unit test can catch a wrong-but-valid hex.

### P2 — Board correctness (highest user-visible impact)
`aitracker/web/ext_cr_board.js`: fold ungrouped agent sessions into a `(no group)` bucket, or include them individually when non-idle (A3); add `failing` to the rank/state table with the `fail: <command>` word (A5).
**Check**: `tests/` assertion — a session list containing `{agent:true, group:""}` non-idle must yield ≥1 tile; a failing session must yield a tile whose state word starts `fail:`. Prove by reverting the fix and watching it go red.
**Risk**: relaxing the filter could flood the board. The 8-cap and sort comparator both verified correct, so overflow is contained — but assert tile count ≤ 8 in the same test.

### P3 — Dead gates (needs a seam decision — see flag below)
Thread `term_attached` (A4), `pinned` (A10), `triage` (A9) and flag **text** (A11) into the existing shared shapes in `registry.py` / `providers/*`.
**Check**: one selfcheck assertion per field, asserting both Claude and Auggie emit it.

> **Flagging as the handoff instructs.** The bundle says *"No server changes expected… If you find yourself needing a new endpoint, stop and flag it."* I am **not** proposing a new endpoint. But A4 has only two routes: (a) the client calls the existing `GET /api/term/attached` per panel — which violates the "no new server round-trips per panel" non-negotiable; or (b) thread the field into the detail dict already served by the 2s poll — a server-side seam change, no new endpoint. **I recommend (b)** and am surfacing it rather than deciding silently.

### P4 — Safety and accessibility
`ext_cr_dialogs.js:1129-1136` Port/Host → `readonlyField(...)` (A6); wire the terminal overlay through the same `trapFocus` + opener-capture as `CR.dialogs`, or drop `role="dialog"` (A7); add scroll preservation to the board container, mirroring the rail's existing logic (A8).

### P5 — Verification (mandatory, not optional)
1. `env -u TRACKER_AUTH make check` → `selfcheck ok` (plain `make check` gives ~33 blanket-401 failures).
2. **`make serve` and load the page in a real browser, console open, in BOTH themes.** The gate does not catch load-time JS errors: everything ships as one script tag, so a throw in any `ext_*` file silently kills every file after it. This exact class already bit this project once (`CR.detail = {}` vs `window.CR.detail`, `ReferenceError` on every page load). A green gate is **not** sufficient evidence.
3. Adversarial pass: second agent told to assume the fixes are false.

C1–C4 are excluded from every phase pending the owner's answer.
