# Control-room refinements — session "tracker-refinements"

Worktree: `.claude/worktrees/control-rail-polish`  branch: `worktree-control-rail-polish`  base: `698a857`
2026-09-05/06. Unattended run (`/head-out`). Skills: `/tracker-gap`, `/tracker-push`, `/head-out`.

## The contract — user's asks, verbatim

1. "The session rail in the control-view UI needs to be a bit clearer and smoother like the old/existing view"
2. "fix the alignment in the control-view UI"
3. "the session markers/pinned and other pieces of information must be same in both the UIs"
4. "the Manage Terminal from the Terminals tab, shows empty after a while, may be after each round of poll"
5. "Get the text beside the symbols/icons/emojis such that it's easily readable to everyone like previously"
6. "Same in this view : get the texts beside the symbols/icons/emojis..." (Sessions/detail view)
7. "the session shows the pinned marker but that marker needs to be clickable such that by clicking we can unpin
   that session, also at the same very place keep a pin with the text such that one can pin the session right
   from that very tab and can seamlessly unpin"
8. "always name the models for the agents"
9. "the dialog box for the dark theme should match the design theme chosen ... Make sure you do not change the
   existing/default UI's default color for the dialog view on that UI"
10. "the color design for the control-view must follow this design theme :
    '/Users/pritammondal/Downloads/app-ui-redesign-request 2'"
11. "the board tab 'working' and others arent working at all"
12. "Do an adversial review for all the items and make sure you fix them all"
13. "make the 2 agents working tab clickable such that one can track the agent live from the session header itself"
14. "adding a default markdown renderer for all the shells and everything such that we dont end up reading raw markdown"
15. "for the links sections make sure you are adding links which are alive if a link has died please remove them
    currently it's too noisy, also add this links section by default on the default/existing dashboard UI such
    that one can use them from both the views"

## Verdict per clause — ALL DISCHARGED

| # | Ask | Status |
|---|-----|--------|
| 1 | Rail clearer/smoother | DONE |
| 2 | Collapsed rail alignment + clipped footer | DONE (incl. 4-digit `+1234` clip found in review) |
| 3 | Marker parity both UIs | DONE (incl. cross-view status parity defect found in review) |
| 4 | Manage-terminals empties after poll | DONE |
| 5 | Text beside icons (board/top bar) | DONE |
| 6 | Text beside icons (detail view) | DONE |
| 7 | Detail-header pin/unpin toggle | DONE |
| 8 | Name agent models | DONE (standing practice; in memory) |
| 9 | Dialog dark theme | DONE (+ light theme, found in review) |
| 10 | Colour system follows handoff | DONE (tokens already conformed; `--scrim` added) |
| 11 | Board counters dead | DONE (a "no defect" verdict was REFUTED by review) |
| 12 | Adversarial review of everything | DONE — 3 review passes, 8 further defects found and fixed |
| 13 | Clickable "N agents running" pill | DONE |
| 14 | Markdown rendering everywhere | DONE (+ `mdSafe` for machine output, found in review) |
| 15a | Dead-link filter | DONE (revised from drop-to-mark; crash found in review) |
| 15b | Links section on classic dashboard | DONE |

## Assumptions taken (user was away — no question round)

- "clearer/smoother like the old view" = adopt the classic sidebar's INFORMATION set, rendered in the control
  room's own design tokens. Not a visual copy of app.css.
- (10) scoped to COLOUR only, not layout/typography/spacing. A full redesign was not assumed.
- (15) "dead link" = a LOCAL path that no longer exists. Remote URLs are KEPT unverified: this app makes no
  outbound network requests and probing URLs would break that invariant. **Flagged to the user — if HTTP
  liveness checks are wanted, that is a deliberate relaxation of the no-network rule and the user's call.**
- (14) markdown is NOT applied to shell COMMANDS, file paths, or PTY output. On machine-output prose
  (shell stdout, agent messages) it uses `mdSafe` — no single-asterisk italics, so `*.py` survives.
- Only the control view changes, except where the user asked for parity (3, 15b).

## Root causes established (evidence)

- **Icon HTML leaking into rail rows AND board tiles.** `ext_cr_board.js:371` `toolLabel()` ran
  `srcLabel(src).replace(/^\S+\s*/,'')`, but `srcLabel` (`app.js:876`) returns HTML from the `SRC` map, so
  `^\S+` stripped only `<svg`/`<span` and the attributes rendered as text. Fixed by deriving the HTML `SRC`
  map FROM a plain-text `SRC_TEXT` map, so the two cannot drift.
- **Manage terminals emptied.** `ext_cr_boot.js:895` broadcast `{flags,sessions,now}` every poll;
  `CR.dialogs.update()` forwarded it to the topmost dialog unconditionally, overwriting its payload;
  `paint()` then read `terminals||[]` -> "0 of 0 running". Fixed structurally (see below).
- **WORKING counter always 0.** `mtime` (`claude.py:538`, `_mtime_and_bg`) folds in background-agent
  activity, but `ended` (`claude.py:204`, `_tail_scan`) reads ONLY the main transcript — so a session with
  agents running is `live` AND `ended` at once, and `live && !s.ended` never counted it. `bg` counts agent
  files with mtime inside `LIVE_WINDOW` (`claude.py:741`), i.e. live-right-now, not ever-ran.
- **White dialog in dark theme.** The "Narration" dialog is NOT a control-room dialog: it is classic's
  `#msgmodal` (`index.html:236`), a DOM SIBLING of `#nextRoot` (`:227`), so control-room tokens never resolve
  on it and every `var(--token, fallback)` uses its literal fallback.
- **Design tokens.** `ext_cr.css` already implemented the handoff's full token set under `.tracker-next` /
  `.tracker-next.is-dark` with no drift. Real gap was three unthemed scrims.

## What the adversarial review pass changed (ask 12)

Three review agents, each told to assume the implementer's report was FALSE. Eight further defects found:

1. **REFUTED a "no defect found" verdict** on the WORKING counter, with a live 90-second reproduction:
   a real `source:'cli'` session with 3 agents running and a 1-3s-old mtime counted as WORKING = 0.
2. **A second dialog had the identical blanking bug** — `renderDirectoryPicker`'s update
   (`ext_cr_dialogs.js:1836`). Fixing one dialog had treated the symptom.
3. **The two UIs disagreed about status** — the board was fixed, classic (`app.js:1016`) was not, so classic
   showed `✓ done` + green row while the board showed `working`. Directly violated ask 3.
4. **`md()` corrupted machine output** — `"ran ruff over *.py and *.js"` -> `"<em>.py and </em>.js"`, on raw
   shell stdout.
5. **A vacuous test** — the rail's half of the WORKING fix was untested; reverting the guard left the suite
   GREEN (76 tests OK) because every fixture defaults `bg: 0`.
6. **`annotate_liveness` crashed on a non-string path** (500 on `/api/session`), and once guarded, a SECOND
   crash surfaced in the provider itself (`TypeError: cannot use 'list' as a dict key`) — the paths are used
   as dict keys. Fixed at the trust boundary (`claude.py`, isinstance guards at ingestion).
7. **Relative and `~` paths were judged against the SERVER's cwd** — `~/.zshrc` marked dead and dropped.
   Now `~` is expanded and relative paths anchor to the session's own `meta.cwd`.
8. **The collapsed footer still clipped at 4 digits** (`+1234` in ~19px) — reachable at 957 sessions.

Reviewers also REFUTED several of my own suspicions, correctly: `renderLinksPanel` does guard against
re-appending (`if(!panel)`); `.cr-flagcount`'s `lastChild` count update is unaffected by the new label span;
all three scrims resolve; the `~` sibling combinator is valid; and widening the `#msgmodal` gate (my
suggestion) would have painted DARK literals in light theme, because the tokens never resolve there.

## Structural fixes (so the bug class cannot recur)

- **Poll broadcast opt-in.** The broadcast is tagged `{kind:'poll'}` at its one call site; `open()` records
  `wantsPoll` per dialog; `update()` refuses to forward a poll payload to a dialog that has not opted in.
  Only the flags list opts in. A new dialog is poll-blind by default.
- **One `isSessionWorking(s, live)`** in `app.js`, used by classic's `sessionRow()` and the board's
  `isWorking()`. The two views cannot drift on status again.
- **One `SRC_TEXT`** with the HTML `SRC` map derived from it.
- **One `deriveLinks()`** in `app.js`, used by both the classic Links panel and the control room's.
- **One `--scrim`** token behind all three scrims.

## Verification bar actually met

- Full gate: `env -u TRACKER_AUTH python3 -m unittest discover -s tests` — ~1600 tests, `selfcheck ok`.
- Bundle syntax check (the gate CANNOT catch this): the app is ONE `<script>` + ONE `<style>`, so a stray
  `throw` or unterminated `*/` kills every file after it while tests stay green. Built via `page.build_page()`
  and ran `node --check` on the concatenated 925KB script: OK. CSS braces 1562/1562, comments 382/382.
- Every behavioural fix proven load-bearing: revert the fix, watch the test go RED, restore.
- ~109 tests added this session.

## KNOWN GAPS / for the user

- **No real browser verification.** The Chrome extension reported "not connected" for every agent and for the
  main session, so nothing was confirmed by eye. The dark/light dialog theming is correct by construction
  (gate selector present on all 45 selector lines, real tokens, DOM order verified) but UNSEEN. Worth a glance.
- **Pin toggle has no revert-on-failure.** A failed `POST /api/pin` leaves the optimistic flip showing the
  wrong state until the next ~2s poll corrects it. Bounded, not stuck. Deliberately skipped: a proper fix
  needs a revert contract across `ext_cr_detail.js` / `ext_cr_boot.js`.
- **`landed` tile state is now rare** for sessions that used background agents: `bg` counts agent files
  touched within `LIVE_WINDOW` (300s), so a session stays "working" for up to 5 minutes after its last agent
  write. This is consistent with the app's own liveness definition but is a deliberate trade.
- **Remote URL liveness is never checked** (no-network invariant). Dead GitHub links stay in the Links panel.
- **Rail kidchip:** classic's inline "N agents" count on a parent row has no rail equivalent; the rail buckets
  agent sessions under collapsible headers instead. Pre-existing architectural difference, documented.

## Process notes

- A subagent REFUSED three mid-run `SendMessage` scope expansions as prompt injection (they were genuine),
  so that work silently did not happen. Put scope in an agent's INITIAL brief; always read a report for a
  refusal. Recorded in memory.
- Four agents were watchdog-killed after running a broad `git diff` on this ~1300-line change. Brief review
  agents to use `grep -n` + `sed -n 'A,Bp'` and never `git diff` or whole-file reads. Recorded in memory.
- `TRACKER_AUTH` must be unset for tests AND for `make serve` (otherwise the server shows a sign-in page).
- The full suite passes alone (~200s) but OOM-kills (exit 137) if two full runs overlap.
