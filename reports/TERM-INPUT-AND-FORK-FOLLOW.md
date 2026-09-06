# Terminal input parity + fork-follow — working record

Branch: `worktree-term-input-and-fork-follow` (worktree
`.claude/worktrees/term-input-and-fork-follow`, based on `06e6c23`).
Skills invoked: `/tracker-gap`, then `/tracker-push`.

## The contract, verbatim

> 1. The keystrokes or mouse select or any mouse actions which is supported by default in the
>    terminal is not functioning as expected in the in-session browser
> 2. The changes made by the in-session terminal  is not updated with the tracker's narration and
>    doesn't really updates anything there. /tracker-gap /tracker-push

And, mid-turn:

> fan-out please treat this session as orchestrator and run multiple agents with cheaper models as
> per the Claude.md

And, later:

> the mouse modes should be supported exactly like how its supported by the claude-code in the
> terminal

This last one raises the bar from "xterm-correct" to "matches the reference implementation's actual
behaviour", which is an empirical question — so it is being answered by capturing the real byte
stream `claude` emits into a real PTY, not from the spec alone. Conventions rule 7 (confirm the
real shape before writing the parser) applies to input streams too.

| # | Clause | Verdict |
|---|--------|---------|
| 1 | Keystrokes behave as a real terminal | **discharged** — xterm modifier encoding, F1-F12, Alt+Enter, Ctrl+Space; proven by executing the shipped `keyToBytes` |
| 1 | Mouse select / mouse actions behave as a real terminal | **discharged** — SGR + legacy reports for press/drag/release/wheel, Shift still gives a native selection; proven by executing the shipped encoder |
| 1 | "supported exactly like claude-code in the terminal" | **discharged** — measured from a real PTY capture of v2.1.245: modes 1000/1002/1003 (1003 effective) + 1006, and `?1004` focus reporting, which was missing |
| 2 | Terminal work is reflected in the tracker's narration/detail | **discharged** — the forked copy is now identified and linked, or honestly left unlinked; never mis-attributed |
| — | `/tracker-gap` procedure (worktree, shared seam, evals + unit tests, `make check`) | **discharged** — landed at `registry.py`'s seam so every provider inherits it; 931 tests |
| — | `/tracker-push` (direct push to `personal/main`, LICENSE intact) | in progress |
| — | Orchestrate via fan-out to cheaper models | **discharged** — 20 agents, all sonnet/haiku, no opus leg |

## Gap 1 — terminal input parity

Framed per `/tracker-gap` step 1.

**Capability, one line.** The in-browser terminal should accept the input a real terminal accepts:
modified keys (Ctrl/Alt/Shift + arrows, Home/End, Enter), function keys, and mouse press / drag /
release / wheel forwarded to any program that asked for mouse reporting — while native browser text
selection still works when no program is asking.

**The asymmetry.** Not Claude-vs-Auggie: this is *server has the information, client never acts on
it*, and *the emulator throws the information away*.

- `aitracker/term_vt.py:799` — `# 1000-1006 (mouse) and any other private mode: no-op`. The
  emulator parses the app's request for mouse reporting and discards it, so no layer downstream
  ever learns a program wants mouse events.
- `aitracker/web/ext_vt.js:328` — the only `mousedown` handler on the pane is
  `function () { input.focus(); }`. No mouse event is ever encoded or sent to the PTY.
- `aitracker/web/ext_vt.js:126` `keyToBytes` — modifiers are dropped rather than encoded:
  `Ctrl+ArrowLeft` falls through to the unmodified `\x1b[D`; `Alt/Shift+Enter` falls through to a
  plain `\r` (so Claude Code's newline-without-submit submits instead); F1–F12 and Ctrl+Space
  return `null` and are swallowed.

**Consumers to reach.** Server: a `mouse_mode` field on `Screen.snapshot()`, plumbed through the
SSE frame emitter the way `bracketed_paste` already is. Client: a mouse handler on `.vtpane` that
encodes SGR (1006) reports, and a `keyToBytes` that encodes the xterm modifier parameter.

## Gap 2 — terminal work not reflected in the tracker

**Capability, one line.** Work done in the in-browser terminal should show up in the tracker.

**Leading hypothesis (under investigation).** A resume that hits Claude Code's
background-agent refusal is retried with `--fork-session`; the tracker already *says* so in a
notice, but the fork is a **copy under a new session id**. The detail page the user is looking at
is the *parent* session, whose transcript stops growing — so nothing they do in the terminal ever
appears there. Confirmed from the user's own screenshots: session "audit bot rel-aug26
configuration" reads `idle 51m ago` with its newest narration entry 23h old, while the standalone
terminal for that same session carries the fork notice.

Open question for the investigation: is the new session id linkable to its parent from on-disk
data? Answer decides between *follow the fork* and *ship the honest note*.

## Investigation fan-out (round 1)

| Agent | Model | Question |
|-------|-------|----------|
| Explore | sonnet | Does the SPA keep polling session detail while the terminal modal / standalone view is open? |
| Explore | sonnet | The fork path server-side, and whether a forked session is linkable to its parent from real `~/.claude` data |
| researcher | sonnet | Canonical xterm modified-key encoding + SGR 1006 mouse protocol, with citations |
| Explore | haiku | How terminal input is tested here, and the `bracketed_paste` plumbing chain to copy for `mouse_mode` |

### Round-1 result — the `mouse_mode` plumbing chain (Explore, haiku)

`bracketed_paste` is the model to copy; four sites, verified:

| Step | Site | Snippet |
|------|------|---------|
| set from the DEC private-mode handler | `aitracker/term_vt.py:798` | `self.bracketed_paste = set_` |
| added to `snapshot()` | `aitracker/term_vt.py:334` | `"bracketed_paste": self.bracketed_paste,` |
| SSE emitter forces a frame on change | `aitracker/term_vt.py:2291` | `or snap["bracketed_paste"] != last_bp` |
| client reads it | `aitracker/web/ext_vt.js:398` | `if (msg.bracketed_paste !== undefined) this.bracketedPaste = !!msg.bracketed_paste;` |

Test style to mirror: `TestSnapshotScreenStateFields`, `tests/test_term_vt.py:314-395` — construct a
`Screen`, `feed()` the escape bytes, assert on `snapshot(-1)`.

There is **no** test asserting mouse-mode state today. There IS a test asserting the *opposite* of
what we are about to build: `TestOutOfScopeConsumed.test_mouse_reporting_modes_are_noop`,
`tests/test_term_vt.py:513` — it must be revised, not deleted, and the module docstring at
`aitracker/term_vt.py:85` ("Mouse reporting … consumed as unknown private DEC modes") stops being
true.

`keyToBytes` has **no** direct test today; keystrokes are covered only end-to-end by
`TestSpawnAndScreen`, `tests/test_term_vt.py:634`.

### Round-1 result — the SPA never stops polling (Explore, sonnet)

A **negative** result that removes the obvious suspect from gap 2. There is no pause/clear/skip
guard for any modal or overlay anywhere:

- `aitracker/web/app.js:951` — `setInterval(loadSide, 5000)`, the sidebar poll.
- `aitracker/web/app.js:955-957` — `poll(); timer = setInterval(poll, 2000);`, the session-detail
  poll. `poll()` (`app.js:1018`) refetches `/api/session?id=…` and re-renders.
- `poll()` has no `document.hidden`, no `.overlay` check, no paused flag. `document.hidden` appears
  once (`app.js:1001`) and only decides whether to fire a browser notification.
- Standalone `?tty=` mode (`ext_vt.js:1551`) only reparents DOM and hides `.app`; `start()`
  (`app.js:1695`) already ran, so both intervals keep firing invisibly.
- `closeVT()` (`ext_vt.js:1494`) does not force a refetch — it does not need to; the 2s cycle
  already covers it.

**So the detail view is refreshing the whole time. It is refreshing the WRONG SESSION.** That is
the fork hypothesis, now the only one standing.

### Round-1 result — the fork discards the only thing that could link it (Explore, sonnet)

This decides gap 2's shape.

- Refusal detection: `aitracker/term_gate.py:170` `looks_like_bg_refusal()`, marker at
  `term_gate.py:83`.
- Tier 2 (in-browser PTY): `aitracker/term_vt.py:1731` `_resume_backstop()` watches the child, and
  on a match calls `_retry_with_fork()` (`aitracker/term_vt.py:1664-1728`), which re-execs
  `claude --resume <sid> --fork-session` and **swaps the new child into the same `Pty` object,
  keeping the same tty id**. It injects the user-visible note at `term_vt.py:1719`.
- **Nothing captures the new session id.** `Pty` has no field for a Claude session id at all
  (`term_vt.py:1264`); `pt.id` is the tracker's own tty handle. `_retry_with_fork()` reuses the
  ORIGINAL `sid` and never reads back the one Claude assigns the fork. A repo-wide search for any
  linking logic found none.
- `POST /api/term/pty`'s `forked`/`notice` (`term_vt.py:1994`) only describe what is knowable
  *before the child emits output* — for a late backstop fork the HTTP response says
  `forked: false, notice: null`. The outcome exists only as the injected screen line and a server
  `print()`.
- Tier 1 (external Terminal.app) is worse: `term_launch.py:100` bakes `(<resume> || <resume>
  --fork-session)` into a shell string and never observes the tab again.
- **No on-disk fork lineage exists.** Verified against a real transcript: `parentUuid` is an
  *intra-session* message-chain pointer (each line's `parentUuid` equals the previous line's own
  `uuid`, same `sessionId`). Real keys present: `sessionId`, `uuid`, `parentUuid`, `cwd`,
  `entrypoint`, `gitBranch`, `version`, `isSidechain`, `timestamp`, `userType`, `type`, plus
  `sessionKind`/`aiTitle`/`customTitle` per `providers/claude.py:105`. Keys that do NOT exist:
  `parentSessionId`, `forkedFrom`, `originalSessionId`, fork-linking `summary`/`leafUuid`.
  `docs/claude-resume-command-matrix.md:32` (produced from real CLI runs) confirms `--fork-session`
  makes a new id and records no back-link.
- Discovery is a blind mtime-sorted glob: `providers/claude.py:246`, `find_session()` at
  `providers/claude.py:10`.

**Consequence.** The forked copy lands as an unrelated top-level sidebar entry with `parentId: ""`,
and the detail panel the user is staring at polls the parent transcript, which has stopped growing.
Exactly the reported symptom.

**Design decision.** The link cannot be recovered from the transcripts, so the tracker must
*record it at the moment it forks* — the only instant the association is knowable. Same philosophy
the resume backstop already uses: react to what actually happened rather than predict it.

### Round-1 result — xterm input protocol, with citations (researcher, sonnet)

Source: xterm `ctlseqs`, Patch #411 (2026/08/23), invisible-island.net. Confidence flagged per item.

- Modifier parameter `Pm = 1 + 1*Shift + 2*Alt + 4*Ctrl + 8*Meta` — CONFIRMED verbatim (p.44).
- Modified cursor keys `CSI 1 ; Pm <letter>` — LIKELY: the append-modifier-before-final-char rule is
  verbatim, and the F3 instance `CSI 1;2R` is printed, but the arrow rows themselves are not.
- Plain editing keys `CSI 2~ 3~ 5~ 6~` and PC-style `CSI H`/`CSI F` — CONFIRMED (pp.42,45).
  Modified `CSI <n>;Pm~` — LIKELY, via the printed F5 instance `CSI 15;2~`.
- F1-F4 `SS3 P/Q/R/S`, F5-F12 `CSI 15/17/18/19/20/21/23/24 ~` — CONFIRMED (p.43).
- Ctrl+Space / Ctrl+2..8 / Ctrl+/ — **UNRESOLVED**; not in ctlseqs. Treated as ASCII C0 convention
  and flagged as such in the code; only Ctrl+Space implemented.
- Mouse modes 9/1000/1002/1003/1005/1006/1015/1016 — CONFIRMED (pp.15-16).
- SGR 1006: `CSI < Pb ; Px ; Py M` press/motion, final `m` for release with the real button number —
  CONFIRMED (pp.51-52). Buttons left/middle/right = 0/1/2; +4 Shift, +8 Meta, +16 Ctrl; +32 motion;
  wheel 64/65 — CONFIRMED (pp.49-50).
- Coordinates 1-based, "The upper left character position on the terminal is denoted as 1,1" —
  CONFIRMED (p.49).
- Shift bypasses mouse tracking for native selection: XTSHIFTESCAPE / `shiftEscape` resource,
  default `Ps=0` "allow shift-key to override mouse protocol" — CONFIRMED (p.27).

## Implementation fan-out (round 2)

File ownership is exclusive so two agents never edit one file.

| Leg | Model | Owns | State |
|-----|-------|------|-------|
| `mouse_mode` on `Screen` + snapshot + SSE + RIS | sonnet | `aitracker/term_vt.py`, `tests/test_term_vt.py` | running |
| `keyToBytes` modifiers + client mouse encoder | sonnet | `aitracker/web/ext_vt.js`, `tests/test_term_vt_client.py` | running |
| fork-follow (gap 2) | — | `term_vt.py` hook, `registry.py`, `store.py`, `web/app.js` | queued behind leg 1 (shares `term_vt.py`) |

### Round-2 result — leg 1, `mouse` on the snapshot (sonnet) — LANDED

Shape published: `"mouse": {"mode": 0 | 1000 | 1002 | 1003, "sgr": bool}`.

| Site | What |
|------|------|
| `aitracker/term_vt.py:246-262` | `_mouse_1000/_mouse_1002/_mouse_1003` flags + `mouse_mode`/`mouse_sgr`, beside `bracketed_paste` |
| `aitracker/term_vt.py:818-834` | the `?1000/?1002/?1003` branches + `?1006`, and `_update_mouse_mode()` implementing 1003 > 1002 > 1000 layering |
| `aitracker/term_vt.py:355` | `"mouse": {"mode": self.mouse_mode, "sgr": self.mouse_sgr},` in `snapshot()` |
| `aitracker/term_vt.py:2337-2361` | `last_mouse` in the SSE emitter's tracked state, so a mode flip forces a frame |
| `aitracker/term_vt.py:1198` | RIS: no code needed — `_reset()` already re-runs `__init__`; docstring corrected to say so |

Docs corrected where they had become false: module snapshot contract (`:17`), the "Explicitly out of
scope" mouse bullet (`:85`), the SSE key enumerations (`:2265`, `:2278`).

Tests: new `TestMouseReportingSnapshot` in `tests/test_term_vt.py` (default, 1000 toggle, 1002/1003
independence, layering fallback, sgr independence, combined sequence, RIS reset, stream integrity,
version-not-bumped). Revised `TestOutOfScopeConsumed.test_mouse_reporting_modes_are_noop` →
`test_mouse_reporting_modes_consumed_without_corrupting_stream`.

Honest contradiction the agent surfaced and fixed rather than worked around:
`TestWireFormat.test_stream_frames_carry_no_event_name` (`tests/test_term_vt.py:1464`) pinned the
exact SSE payload key set and had to gain `"mouse"` — a real wire-contract change, recorded here so
it is not mistaken for a test being bent to pass.

Full suite after this leg: **819 tests, OK, `selfcheck ok`.**

To verify adversarially at integration: the RIS claim (that `_reset()` genuinely re-runs `__init__`
and therefore clears mouse state) is the one assertion in this leg that rests on the implementer's
own reading rather than on a site I briefed.

### Round-2 result — leg 3, client key + mouse encoding (sonnet) — LANDED

| Site | What |
|------|------|
| `aitracker/web/ext_vt.js:126-183` | `keyToBytes` rewritten around `var pm = 1 + shift + 2*alt + 4*ctrl + 8*meta` |
| `aitracker/web/ext_vt.js:~270` | `this.mouse = { mode: 0, sgr: false }` + `_mouseButtonDown` / `_lastMouseCell` |
| `aitracker/web/ext_vt.js:~343` | `mousedown` now also calls `self._onMouseDown(ev)`; new `mousemove` / `mouseup` listeners |
| `aitracker/web/ext_vt.js:~407` | reads `msg.mouse` defensively, same shape leg 1 publishes |
| `aitracker/web/ext_vt.js:703-812` | `_mouseGate`, `_mouseCell`, `_mouseButtonCode`, `_sendMouseReport`, `_onMouseDown/Move/Up`, and `_onWheel` with the report branch prepended above the untouched scrollback path |

Keys now encoded: modified arrows, Home/End, Insert/Delete/PageUp/PageDown, F1-F4 (SS3 plain,
CSI-with-leading-1 modified), F5-F12, Alt+Enter → `\x1b\r`, Ctrl+Space → `\x00`. Plain `Ctrl+C` →
`\x03` still unconditional. Deliberately NOT implemented: Ctrl+2..8 and Ctrl+`/` — unconfirmable
from the primary source, so not guessed.

Mouse gate order: `mode === 0` → today's behaviour; `shiftKey` → today's behaviour (XTSHIFTESCAPE);
`viewingHistory` → never report; else encode and send. Motion throttled to one report per cell
change. SGR release uses lowercase `m` with the real button; legacy release reports button 3 and
clamps coordinates at 223.

Tests: `TestModifierAwareKeyEncoding` (10) + `TestMouseReportingIsGatedAndThrottled` (15) in
`tests/test_term_vt_client.py`. **RED check: 24 of 25 fail against the pre-change file**; the
survivor is a regression guard pinning pre-existing scrollback behaviour, which correctly holds in
both versions. File restored byte-for-byte afterwards (`diff -q` clean). `node --check` passes.
`tests.test_term_vt_client`: 138 tests, OK.

### Round-2 result — what Claude Code ACTUALLY emits (measured, sonnet)

Raw `pty` capture, Claude Code **v2.1.245**, `TERM=xterm-256color`, 6059 bytes kept at
`…/scratchpad/capture3_raw.bin`. This is the answer to "support it exactly like claude-code in the
terminal" — measured, not inferred.

Ordered, and none of them ever reset:

    \x1b[?25h \x1b[?25l \x1b[?2004h \x1b[?1004h \x1b[?2031h
    …on entering the main TUI…
    \x1b[?1049h \x1b[?1000h \x1b[?1002h \x1b[?1003h \x1b[?1006h

| Mode | Claude Code | Us |
|------|-------------|-----|
| `?1000` / `?1002` / `?1003` | all three set, in that order | leg 1 resolves to **1003**, the last-set and most inclusive — matches |
| `?1006` SGR coords | set | supported |
| `?1004` focus reporting | **set** | **was missing** → leg 4 |
| `?2004` bracketed paste | set | already supported |
| `?1049` alt screen, `?25` cursor | set | already supported |
| `?2031` | set at startup | consumed as a no-op; meaning **not determined**, deliberately not guessed |
| `?9`, `?1005`, `?1015`, `?1016`, `?1` DECCKM, `?7`, `?2026`, `?2027` | **not used** | nothing owed |

Two things this measurement changes:

1. `?1004` is a real gap — Claude Code asks for focus events and we never send `\x1b[I` / `\x1b[O`.
2. Because the effective mode is **1003 (any motion)**, every cell crossing produces a report. The
   send path is one fire-and-forget `fetch()` per call with **no sequencing**, so concurrent POSTs
   can arrive out of order. That is a pre-existing latent bug (fast typing can transpose
   characters); any-motion tracking turns it from rare into routine.

### Round-2 — leg 4 dispatched (sonnet)

Owns `term_vt.py`, `ext_vt.js`, `tests/test_term_vt.py`, `tests/test_term_vt_client.py`. Scope:
`focus_events` published on the snapshot and sent by the client; motion coalesced to one report per
animation frame (press/release/keystrokes never coalesced); `_send` serialized through a promise
chain so bytes cannot arrive out of order; `?2031` documented as consumed-and-unexplained.
Also re-verifies leg 1's unproven RIS claim.

### Round-2 result — leg 2a, fork lineage recorded and rendered (sonnet) — LANDED

| Site | What |
|------|------|
| `aitracker/config.py:22-28` | `FORKS_FILE` beside the other app-state files, same late-bound pattern; `.gitignore:6` |
| `aitracker/store.py:93-211` | `record_fork(parent_sid, cwd, at)` (idempotent upsert, never clobbers a resolved child), `resolve_fork_child(parent_sid)`, `fork_parent_of(child_sid)`, `_first_cwd(path, max_lines=20)` |
| `aitracker/registry.py:~26-45` | `all_sessions()` stamps `continued_as` / `continued_from` on **every** session dict, every provider — one implementation |
| `aitracker/registry.py:~63-77` | `parse_any()` stamps the same two keys on the detail dict; `None`-for-unknown-id preserved |
| `aitracker/web/app.js:1025-1067` | `renderForkLinks(d)` — prominent banner when forked, quiet back-link when a fork; both call the sidebar's existing `pick()`, no second nav path |
| `aitracker/web/app.css` | `.forkbanner` / `.forkbanner.quiet` on existing tokens, no viewport or host gating |

Resolution rule: glob `PROJECTS/*/*.jsonl`, exclude the parent's own file, require `mtime >= at - 5`
and a matching first-line `cwd`, take the oldest qualifying candidate, then **memoize the answer
back into `forks.json`** so the 2s poll never rescans. Non-parents fast-path to `""` on a single
dict lookup.

Deliberate scope call, correctly reasoned: the seam ships the linked session's **id only**, not its
title — resolving a title would mean parsing the other session on every poll, and the client
already has every id's title from its own list poll. That respects "server owns policy" without
paying for it twice.

Tests: `tests/test_fork_follow.py`, 11 tests — record+resolve, parent never matches itself, cwd
mismatch rejected, pre-fork-instant rejected, oldest-of-several wins, unresolved returns `""`,
memoization survives the source directory being deleted, malformed/empty JSONL tolerated, reverse
lookup, and the shared-seam proof that an **Auggie** session gets `""`/`""` through the identical
code path. Full suite: **861 tests, OK, `selfcheck ok`.**

Interface note for the call site still to come: `record_fork` wants a unix-epoch `at` and the
terminal's cwd **verbatim** — `resolve_fork_child` compares it without path normalisation.

### Round-2 result — leg 4, focus reporting + send-path integrity (sonnet) — LANDED

| Site | What |
|------|------|
| `aitracker/term_vt.py:267` | `self.focus_events = False` |
| `aitracker/term_vt.py:849` | `elif code == 1004: self.focus_events = set_` |
| `aitracker/term_vt.py:373` | `"focus_events": self.focus_events,` in `snapshot()` |
| `aitracker/term_vt.py:2341,2369,2383` | `last_focus_events` in the SSE change-detection tuple |
| `aitracker/web/ext_vt.js:321,490` | `this.focusEvents` + defensive read of `msg.focus_events` |
| `aitracker/web/ext_vt.js:408-419` | existing focus/blur listeners now send `\x1b[I` / `\x1b[O`, gated |

**RIS re-verified independently** (the open item flagged against leg 1): `_reset()` (~`:1210`) does
`self.__init__(cols, rows)`, and `focus_events` is initialised there — read directly, not taken on
trust, and pinned by `test_ris_resets_focus_events`.

Two send-path fixes that any-motion tracking forced into view:

- **Coalescing** — only motion is coalesced, via `_sendMotion` holding the newest pending report and
  flushing once per `requestAnimationFrame`. `_sendMouseReport` gained an `isMotion` flag that ONLY
  `_onMouseMove` passes; press, release, wheel, keystrokes and pasted text all bypass it. Motion is
  the one event where only the latest value matters; everything else is a discrete transition.
- **Ordering** — `_send` now queues onto one per-instance promise chain, so bytes reach
  `/api/term/keys` in production order regardless of `fetch()` resolution order. The `.catch()` sits
  *inside* the chain so a failed send cannot wedge every later one. This was a **pre-existing latent
  bug**: fast typing could already transpose characters; 1003 would have made it routine.

`?2031` documented as consumed-and-unexplained; no behaviour invented for it.

Tests: `TestFocusReportingSnapshot` (6), `TestFocusReportingClient` (5),
`TestSendOrderingAndMotionCoalescing` (12). Wire-format key-set test updated to include
`focus_events` — legitimate, that test exists to catch exactly this drift. RED check: **21 of 26
red** against pre-change files; the 5 survivors pin invariants that were already true. Files
restored byte-identical (`diff -q` clean). Full suite: **879 tests, OK.**

## Verification ledger

**Gate:** `make check` on the integrated tree — **882 tests, OK, `selfcheck ok`.**

**Executed browser proof (orchestrator).** The client tests are source-text assertions (no JS engine
in the stdlib), so they cannot prove the encoder RUNS. To close that hole, a throwaway server was
started on port 8912 from this worktree (the user's 8787 dashboard untouched), the real page fetched,
and the **shipped** functions extracted from the served bundle and executed in the browser.

`keyToBytes`, real output — every case matches ctlseqs, and plain keys correctly emit no `;1`:

| Input | Bytes | Input | Bytes |
|---|---|---|---|
| ArrowLeft | `ESC[D` | Ctrl+ArrowLeft | `ESC[1;5D` |
| Shift+ArrowUp | `ESC[1;2A` | Alt+ArrowRight | `ESC[1;3C` |
| F1 | `ESC O P` | Ctrl+F1 | `ESC[1;5P` |
| F5 | `ESC[15~` | Shift+F5 | `ESC[15;2~` |
| F12 | `ESC[24~` | Ctrl+Delete | `ESC[3;5~` |
| Home | `ESC[H` | Ctrl+Home | `ESC[1;5H` |
| Enter | `\r` | Alt+Enter | `ESC \r` |
| **Ctrl+C** | **`\x03`** | Ctrl+Space | `\x00` |
| Tab | `\t` | Shift+Tab | `ESC[Z` |

`ESC[15;2~` and `ESC[1;5P` are the two forms printed verbatim in the xterm doc — the implementation
reproduces them exactly. Ctrl+C still SIGINTs.

Mouse path, executed against a fake terminal capturing sends:

| Action | Bytes | Verdict |
|---|---|---|
| left press col 12 row 5 | `ESC[<0;12;5M` | 1-based, button 0 |
| drag one cell right | `ESC[<32;14;5M`, still pending in the rAF | +32 motion bit, coalesced not sent |
| release | `ESC[<0;14;5m` | lowercase `m`, REAL button (not 3) |
| wheel up / down | `ESC[<64;1;1M` / `ESC[<65;1;1M` | 64 / 65 |
| legacy right press / release | `ESC[M",%` / `ESC[M#,%` | button 2; release forced to 3, coords clamped |
| `mouse.mode === 0` | nothing sent | gate closed |
| Shift held | nothing sent | XTSHIFTESCAPE bypass works |

Also confirmed by reading the shipped source: `_mouseCell` derives coordinates from
`rowsEl.getBoundingClientRect()` (not the padded pane), `_mouseGate` orders the checks
mode → shift → viewingHistory, `_sendMotion`'s rAF flush goes back through `_send` so **coalesced
motion and discrete events share ONE ordering domain**, and `_send`'s `.catch` sits inside the chain
assignment so a rejected send cannot wedge later ones.

**Wire proof:** a live SSE frame from `/api/term/screen` carries the new fields:
`"mouse": {"mode": 0, "sgr": false}, "focus_events": false`.

Harness note, recorded so it is not mistaken for a defect: an attempt to flip mouse mode by typing
`printf '\033[…]'` into a spawned shell failed because the shell's line editor echoes raw ESC in
caret notation, so the bytes never reached the emulator. That was the test harness's fault, not the
code's; the executed-encoder proof above replaced it.

## Adversarial review — round 3 (reviewers told to assume the reports are FALSE)

Both reviewers executed code rather than reading it. Between them they refuted **five** claims.

### Input parity — 2 HIGH defects, both reproduced under Node

1. **Motion/discrete reordering.** `_send` appends to the chain at ENQUEUE time; `_sendMotion` only
   appends when its `requestAnimationFrame` fires. A discrete event produced *after* a motion can
   therefore be appended *first*. Reviewer's executed proof: a motion at t=0 and a `_send` at t=5ms
   (before the 16ms rAF) POST as `RELEASE` then `MOTION`. That is precisely "a release delivered
   before the motion that preceded it" — the thing the chain's own comment claims to prevent. My
   own browser check MISSED this: I verified the flush goes *through* `_send`, but not *when*.
2. **Stuck drag.** Listeners are on `pane` only — no pointer capture, no document fallback. Press
   inside, drag out, release outside → `_onMouseUp` never runs, `_mouseButtonDown` stays set, and
   every later plain hover reports as a drag with a stale button and the `+32` bit.
3. MINOR: `_mouseButtonCode`'s comment claims a Shift bit the code does not encode (inert — Shift
   always bypasses the gate — so the fix is to delete the false comment, not add dead code).

Confirmed intact: the `Pm` formula and every key encoding, plain-`Ctrl+C`→`\x03`, the gate order,
`rowsEl`-based coordinates, focus reporting, mouse-mode layering and RIS.

### Fork-follow — the mis-attribution risk is REAL, reproduced three ways

`resolve_fork_child` identifies the child by `(cwd, mtime)` alone, and that is not enough:

1. **Permanent mis-attribution.** An unrelated session started in the same cwd shortly after the
   fork is returned as the child **and memoized forever**. When the real child later appears, the
   wrong answer stands; there is no re-check path. Recovery requires hand-editing `forks.json`.
2. **mtime is last-modified, not created.** An ancient unrelated transcript in the same cwd that
   merely gets appended to after the fork instant qualifies and, being "oldest", **beats the real
   child even when the real child is already present**.
3. **The `at - 5` tolerance** lets a session created *before* the fork win outright.

Also found, beyond the claims:

4. **Unbounded rescan.** For a recorded-but-UNRESOLVED parent, every `all_sessions()` (5s) and
   `parse_any()` (2s) re-globs `~/.claude/projects/*/*.jsonl` — **1683 files on this machine** — and
   re-opens up to 20 lines of each. If a parent never resolves (one cwd string mismatch is enough),
   that runs forever.
5. **`_save_json` is not concurrency-safe.** `store.py:13` writes through a FIXED `path + ".tmp"`.
   Ten concurrent `record_fork` calls for ten different parents: 9 of 10 raised `FileNotFoundError`
   on `os.replace` and **only 1 record survived**. This helper is shared with
   flags/titles/pins/notes, so the weakness is not confined to this feature.

And the tests could not have caught any of it: `test_oldest_of_several_candidates_wins` only pits
two brand-new candidates created strictly after the fork instant against each other. All 14 tests
pass whether or not the defect exists.

**Judgment: gap 2 does not ship in this form.** A feature that confidently sends the user to an
unrelated session, permanently, is worse than the bug it fixes. The `(cwd, mtime)` heuristic is
being replaced with a signal that actually identifies a fork — currently being measured against
real transcripts rather than assumed.

## Round 4 — the measured fork signal, and the rebuild

An empirical scan of **1686** real transcripts under `~/.claude/projects` found **8 genuine fork
pairs** across 3 repos, with no synthetic session needed.

What a fork actually is on disk: a **logical copy of the parent's message chain**. Parent and child
share the same `uuid` values on their early messages (14 to 508 shared uuids per observed pair).
`uuid` is a random UUID4 per message, so an unrelated session cannot reproduce them.

Re-confirmed: **no field in the child ever names the parent's session id** — grepping a child for
its parent's id returns 0 matches. The uuid overlap IS the link; there is no shortcut.

Two details that would have bitten a guessed implementation:
- one observed fork variant keeps the **parent's own unrewritten `sessionId`** on copied lines for
  part of the file, so `sessionId` matching would misfire — the uuid predicate covers both variants;
- bookkeeping lines (`type` of `mode` / `queue-operation` / `last-prompt`) carry **no `uuid`**, so
  a naive "read `uuid` from every line" would raise.

**The predicate, zero false positives across all 8 pairs:** collect the `uuid` of each of the first
~20 lines of parent and candidate that has one; **≥ 3 shared uuids ⇒ candidate is the fork child.**

Explicitly NOT established, and recorded as such rather than assumed: whether `--continue` or
compaction can also duplicate uuids. No example of either was found in the scan.

Rebuild dispatched. Public names/signatures unchanged so the existing call site and seam are
untouched. mtime is demoted to a cheap prefilter and may never DECIDE; the search narrows to the
parent's own project directory; unresolved parents give up after a bounded window instead of
re-globbing 1683 files every 2 seconds forever; `_save_json` gets a unique temp name (fixing
flags/titles/pins/notes too) and `record_fork`'s read-modify-write is serialised.

### Round 4 result — input defects fixed (sonnet) — LANDED

- `aitracker/web/ext_vt.js:744` `_enqueue(s)` — the ONE place that appends to `_sendChain`.
- `aitracker/web/ext_vt.js:750` `_flushMotion()` — drains `_pendingMotion` via `_enqueue`; no-ops
  when already null, so a late rAF cannot double-send.
- `aitracker/web/ext_vt.js:757` `_send(s)` — now `this._flushMotion(); this._enqueue(s);`.
- `aitracker/web/ext_vt.js:779` — the rAF callback calls `_flushMotion()`, never `_send()`, which is
  what makes `_send → _flushMotion → _send` recursion impossible.
- `aitracker/web/ext_vt.js:406-429`, `:784-789` — document-level `mouseup` fallback, skipped when
  `pane.contains(ev.target)` (so no double-send on an in-pane release), clearing the drag state
  unconditionally; removed in `destroy()`, mirroring the existing `_onDocClick` pattern.
- `aitracker/web/ext_vt.js:792-797` — the false Shift-bit comment replaced with the truth.

New `tests/test_term_vt_exec.py` — **8 tests that EXECUTE the shipped JS under Node**, guarded by
`skipUnless(shutil.which("node"))` so `make check` still passes without node and nothing is added to
packaging. This is the direct answer to the reviewer's fair criticism that every client test was a
source-grep that "passes today and would keep passing with the defect fully intact".
RED check: removing `this._flushMotion()` from `_send` reproduces the exact reviewer failure
(`['RELEASE-at-t5', 'MOTION-at-t0']`). Suite: **902 tests, OK.**

**Independently re-verified by the orchestrator** against the rebuilt served page, because the
previous ordering claim had already proven false once:

| Scenario | Result |
|---|---|
| motion at t0, discrete `_send` at t+5ms (before the rAF) | `MOTION-at-t0`, `RELEASE-at-t5` — correct order |
| `PRESS`, motions M1/M2/M3, `UP` | `PRESS`, `M3`, `UP` — coalesced to the latest, and strictly between the discretes |

Coalescing and ordering now hold simultaneously; no double-send.

### Round 4 result — fork resolver rebuilt on uuid lineage (sonnet) — LANDED

Public signatures unchanged, so `term_vt.py:1800` and `registry.py` needed no edit.

Record shape now stored in `forks.json`:

    {"<parent_sid>": {"at": …, "cwd": …, "child": "", "abandoned": false,
                      "parent_uuids": [...], "parent_dir": ".../projects/-work-repo"}}

`parent_uuids` / `parent_dir` are captured once inside `record_fork` (`store.py:183-221`) — at the
one moment the parent is guaranteed readable.

| Concern | Resolution |
|---|---|
| decision signal | `len(parent_uuids ∩ candidate_uuids) >= UUID_MATCH_THRESHOLD` (=3, `store.py:137`) |
| mtime | demoted to a `>= at-5` **prefilter**; never decides |
| scan breadth | parent's own project dir; widens to all of `PROJECTS` only when the narrow dir has **zero candidate files** |
| unbounded retry | `GIVE_UP_SECS = 15*60`, then `abandoned` and a fast-path `""` |
| fast paths | unrecorded / abandoned / memoized → single dict lookup, zero I/O |
| `_save_json` fixed `.tmp` | unique temp name per call, then `os.replace` — fixes flags/titles/pins/notes too |
| lost concurrent records | `_update_forks(mutate)` under an exclusive `fcntl.flock` on `forks.json.lock` (gitignored) |
| unreadable parent | empty fingerprint ⇒ never guesses; stays unresolved until give-up |

`test_oldest_of_several_candidates_wins` **deleted** — it encoded the old wrong behaviour and passed
either way. Five new tests, one per reproduced defect, plus threshold pinning, bookkeeping-line
tolerance, give-up, no-scan-for-unrecorded-sid, a 25-thread concurrent `record_fork` test and a
30-thread `_save_json` test.

RED check: 6 failures + 1 error against the old resolver. Notably the agent found its own
`test_defect3` fixture passing against the old code **by accident** (it used a 3600s-old file the
old floor already rejected), and tightened it to 3s-before so it genuinely exercises the old `at-5`
tolerance. That is the discipline this whole round was about.

Suite: **911 tests, OK, `selfcheck ok`.**

### Round 5 — re-review of both fixes (in flight)

A fix verified only by its author is not verified. Both reviewers re-dispatched, told again to
assume the reports are false. Highest-value open question: **fork-of-a-fork.** A grandchild shares
early uuids with both its parent and its grandparent, so the predicate could plausibly claim it for
the wrong ancestor — the one mis-attribution route the new design might not close.

### Round 5 result — input parity re-review: **SHIP** (reviewer, sonnet)

Everything executed under Node against the shipped functions, not read.

Confirmed: ordering holds under aggressive interleaving (motion/motion/keystroke/motion/mouseup/
wheel/keystroke) **including a rAF firing while a send is in flight**; no double-send under any
tested sequencing; motion keeps flowing across many frames; a rejected send does not wedge the chain
and later sends stay ordered; the document `mouseup` listener uses reference-identity add/remove,
does not leak across two `Terminal` instances, and does not double-send an in-pane release;
`pane.contains` is correct for child elements and detached subtrees. Regression sweep clean —
`Ctrl+C` → `\x03`, `Pm === 1` plain forms, gate order, `rowsEl` coordinates all unchanged, and the
diff never touches `_onKeyDown`'s gate/switch at all.

The reviewer also validated the exec suite is not vacuous: reverting the ordering fix turns 2 of 8
red with the exact original failure; removing the `pane.contains` guard turns exactly 1 red.

Two non-blocking follow-ups it found, both now dispatched:

1. `destroy()` does not clear `_pendingMotion`/`_motionRAFPending` nor cancel the scheduled rAF —
   executed proof shows a stray `postKeys` **after teardown**. Low severity (tty ids are uuid4, so
   misrouting is unrealistic) but free to fix.
2. **A regression class the tests could not catch.** Injecting a plausible bug — dropping
   `_motionRAFPending = false` from the rAF callback — makes motion die silently after the first
   flush (5 drag frames, only the first delivered). **All 8 exec tests still passed.** No test drives
   more than one flush cycle. This is the same "test that cannot fail" pattern found earlier, and it
   is being closed with a multi-frame test that must be proven RED against the broken variant.

### Round 5 result — fork resolver re-review: **DO NOT SHIP** (reviewer, sonnet)

The fork-of-a-fork attack succeeded. Everything below was reproduced by execution.

**Defect A (High).** `store.py:305-319` sorts candidates by **mtime ascending** and `store.py:335-346`
returns the FIRST one past the uuid threshold. So whenever more than one candidate clears the
threshold, **mtime decides after all** — contradicting the module's own comments at `:127` and `:264`.

Scenario: A forks to B; later B forks to C. A fork copies the parent's chain, so C shares ≥3 early
uuids with A transitively. B stays active, so its mtime is bumped past C's.

- `resolve_fork_child("A")` → **`C`** (wrong; the answer is B — C is A's *grand*child)
- `resolve_fork_child("B")` → `C`
- C is therefore claimed as the direct child of **two** parents at once, both memoized permanently.
- Confirmed at the seam: `all_sessions()["gpA"]["continued_as"] == "gpC"`.

**Defect B.** Two direct forks of one parent: the earliest-*mtime* one wins — again by mtime, not by
any principled rule.

**Also:** `registry.py:37`'s `continued_from = {c: p for p, c in continued_as.items()}` has no
conflict handling, so with two parents claiming one child the winner depends on dict iteration
order and disagrees with `fork_parent_of`'s own first-match scan. And the widen fallback costs a
measured **900 `glob.glob()` calls** over a 15-minute unresolved window.

**And another test that cannot fail:** neutering `UUID_MATCH_THRESHOLD` to 0 still left
`test_defect5` passing — it asserts the candidate is *found*, never that uuid overlap *decided*.
(The five numbered defect tests plus the threshold test do genuinely go red, so the suite is not
vacuous overall.)

Confirmed sound and left alone: sub-threshold and empty-fingerprint handling, `fork_parent_of`
consistency, `flock` release on the error path (no truncation, no reentrancy, not held across the
expensive scan), no new file-handle leaks under `-W error::ResourceWarning`, the seam wiring for
every provider, `parse_any(unknown) is None`, and the `term_vt.py:1800` call site.

### Round 6 — the actual fix

The flaw is ordering candidates by **last-modified**. mtime rises merely because a session stays
active, which is precisely why an ancestor or an unrelated session can jump the queue. The property
that identifies the child is *the transcript that came into existence when we forked* — i.e.
**creation** time, `st_birthtime`, which an earlier empirical check found populated and meaningful on
this APFS volume (a real fork child's birthtime landed within 0.5s of its first post-fork message).

New rule dispatched: the uuid predicate stays the **correctness gate**; among candidates that pass
it, choose the **earliest created at-or-after the fork instant**, with an explicit, documented,
deterministic tie-break. A later fork-of-a-fork is created later and therefore loses. Plus: make
`registry.py`'s reverse map agree with `fork_parent_of`, throttle the wide scan, and rewrite the
test that cannot fail so a decoy that wins on timestamps but fails the uuid gate proves the uuid
predicate is what decides.

### Round 6 result — gap 1 follow-ups (sonnet) — LANDED, gap 1 CLOSED

- `aitracker/web/ext_vt.js:~335` — `this._motionRAFHandle = null;` kept solely so `destroy()` can
  cancel the frame.
- `aitracker/web/ext_vt.js:777` — `_sendMotion` captures the rAF id and nulls it the instant the
  callback fires, before anything else; since `_motionRAFPending` guarantees only one frame is ever
  outstanding, a stale handle can never cancel a newer frame.
- `aitracker/web/ext_vt.js:796` — `destroy()` cancels the frame and clears
  `_motionRAFHandle`/`_motionRAFPending`/`_pendingMotion`. Clearing `_pendingMotion` is an
  independent second guard: even if cancellation failed, the flush would have nothing to send.
- `tests/test_term_vt_exec.py` — `TestDestroyCancelsScheduledMotion` (2) and
  `TestMultiFrameMotionRegression` (1), driving **five separate** flush cycles.

RED proof for the regression the reviewer synthesized — dropping `_motionRAFPending = false`:

    AssertionError: Lists differ: ['frame1'] != ['frame1','frame2','frame3','frame4','frame5']

That transcript is now embedded in the test class's own docstring. `tests/test_term_vt_exec.py`:
11 tests, all RUN (none skipped). Suite: **914 tests, OK.**

**Gap 1 verdict: complete and cleared to ship.**

### Round 6 result — fork resolver refuted a THIRD time (reviewer, sonnet)

`resolve_fork_child("B")` returns **`A`, B's own grandparent**. A's early uuids are a strict subset
of B's (B is a copy of A's chain), so A clears the uuid gate against B; the `at - 5` floor is keyed
to B's *fork-into-C* instant, so when B forks again within ~5s of B's own creation A also clears the
floor; A was created before C, so earliest-created hands back A. Structurally impossible — A
predates B — yet returned. On real files with real `st_birthtime`:

    gap=0.00s → resolve(B)='realA'   (expected 'realC')
    gap=4.50s → resolve(B)='realA'
    gap=5.50s → resolve(B)='realC'   correct only once the gap clears the floor

And the shipped regression test for exactly this shape used a **1000-second** gap — comfortably
outside the floor, so it was blind to the bug it was written to catch. A fix correct on the
reproduced input and broken on its sibling.

`st_birthtime` itself was cleared: distinct, monotonic, sub-100ms resolution here. The defect is
algorithmic, not precision. Also confirmed cheap and correct: `registry.py`'s per-session
`fork_parent_of` (pure dict scan, no extra I/O).

### The pattern, and the change of approach

Three rounds, three different mis-attributions, one root cause: **a timestamp heuristic deciding
which of several uuid-matching transcripts is the child.** In a directory full of copies of one
another, ordering by any timestamp is intrinsically ambiguous, and each round's fix just moved which
sibling case broke.

Round 7 replaces the heuristic with an **exact fact**: at the instant we fork we can enumerate which
transcripts already exist, and the child is one that did **not**. Set membership, not ordering.
That structurally excludes every failure so far — ancestors, unrelated older sessions, touched-mtime
files and pre-fork sessions were all already present. The uuid gate stays as the second exact
condition; timestamps are demoted to a documented tie-break for the one genuinely ambiguous case
(the same parent forked twice in one window). The widen-to-all-projects fallback is deleted with its
throttle, which also removes the measured 900-glob cost — if the child never appears in the parent's
own project dir, the honest answer is "don't know" until the give-up window closes.

**Time-box:** this is the last attempt for gap 2. If the next adversarial pass refutes it again,
gap 1 ships alone and gap 2 is reported as not-shippable with the evidence, rather than shipping a
feature that confidently points at the wrong session.

### Round 7 result — approach VINDICATED, one narrow fail-open bug (reviewer, sonnet)

Gate: **923 tests, OK, `selfcheck ok`.**

The snapshot approach holds. All three previously-refuted mis-attributions are closed:

- the round-3 killer (`resolve_fork_child(B)` → `A`) passes at **real** gaps 0/1/3/4.5/10s, on real
  files with no `_creation_time` mocking — the exact shape that hid the last defect;
- fork-of-a-fork is now **causally guaranteed**, not merely observed: C cannot exist before B forks,
  so C's creation always postdates B's, and the tie-break structurally always picks B;
- the widen fallback and its throttle state are genuinely gone; `flock` concurrency holds (25
  concurrent `record_fork`, 30 concurrent `_save_json`); the seam and call site are intact.

The reviewer independently reproduced the `os.utime`/`st_birthtime` drag quirk the implementer had
disclosed, and audited the suite for tests that cannot fail — **found none** this round.

**The remaining defect (High).** `store.py:314` does `except OSError: pre_existing = []`.
`parent_uuids` and `pre_existing` come from two INDEPENDENT I/O calls, but the docstring treats them
as one fused precondition. Fail the directory listing alone — transcript read fine — and:

    pre_existing: []          parent_uuids: 6   → "stay unresolved" fast-path never fires
    resolve_fork_child → 'peOldSibling'          (a genuinely PRE-EXISTING stale sibling fork)

Gate 1 becomes a no-op and resolution falls back to the ordering heuristic that broke rounds 1-3.
Silent (the OSError is swallowed unlogged) and permanent (wrong child memoized; `record_fork` is
idempotent so the bad snapshot is never retaken, even across a restart).

Plus one unproven-but-unmitigated assumption: the snapshot is taken at `term_vt.py:1800`, AFTER
`_fork_child` execs the real binary at `term_vt.py:1492`. If the child writes its transcript in that
window it lands in `pre_existing` and is never findable. It degrades safe (never resolves) rather
than wrong — but it is the one ordering assumption the design rests on, and it is untested.

### Round 8 — the narrow fix, and a note on the time-box

I said round 7 was the last attempt. I am taking one more, deliberately, because the character of
the finding changed: rounds 1-3 refuted the **approach**; this refutes one `except OSError` that
fails **open** instead of **safe**. The reviewer independently judged it "fixable in one more,
narrowly-scoped round, not a sign the approach is unsound". Extending on that basis is honest;
extending because I want the feature to work would not be.

Dispatched: distinguish "snapshot empty" (legitimate) from "snapshot failed" (unusable) with a
sentinel and refuse to resolve on the latter — retry, then give up, never guess; retry the listing a
couple of times and stop swallowing the error silently; move the snapshot to BEFORE the exec so the
ordering guarantee becomes structural rather than assumed; and drop the fat snapshot from the record
once the child is resolved.

**Hard stop:** if the next pass refutes again, gap 1 ships alone and gap 2 is reported unshippable
with all the evidence.

### Round 8 result — one collision closed, its twin confirmed (reviewer, sonnet)

Gate: **930 tests, OK, `selfcheck ok`, run twice with no flake.**

**Attack 1 REFUTED — the interlock is sound.** The `pre_existing` pop and its paired `child=` /
`abandoned=True` set happen in the SAME `_update_forks` mutation under one `flock`
(`store.py:225-250`, `:479`, `:520-536`), and `resolve_fork_child` checks `abandoned` then `child`
(`store.py:470-478`) **before** ever reading `pre_existing` (`:495`). No production writer ever
clears `child` back to `""`. A legitimately-shrunk record therefore cannot fall into the
refuse-branch. The two tests that reset `child` by hand are exercising a state production never
produces.

**Attack 3 CONFIRMED — the twin collision, exactly as predicted.** `record_fork`'s `snapshot=None`
means BOTH "no snapshot, self-capture" and "the pre-exec capture failed"
(`term_vt.py:1751-1756`'s `except Exception: fork_snapshot = None`). So on that branch
`store.py:404-419` self-captures **after** `_fork_child` has exec'd. Reproduced against the real
functions:

    pre_existing recorded: ['parentX', 'childY']   <- the CHILD in its own exclusion set
    resolve_fork_child('parentX') -> ''             <- '' for the full 15-min window, then abandoned
    capture_fork_snapshot call count: 2             <- the post-exec call really happened

And `record_fork`'s docstring claim that "production always passes an explicitly pre-captured
snapshot" is false on precisely this branch.

**Severity is different in kind from rounds 1-3.** This loses the link; it never assigns a wrong
one. Fail-safe, not fail-wrong. Untested because the existing coverage only drives the happy path,
and `test_record_fork_exception_does_not_break_the_retry` mocks `record_fork` wholesale so it never
reaches the internal fallback.

Trigger surface is narrow (every OS-level failure inside `capture_fork_snapshot` is already caught;
the reviewer could only reach it via something like a `RecursionError` escaping `_scan_early`) — but
`term_vt.py`'s own `except Exception` is an explicit admission that failure here is anticipated, and
it currently wires that anticipated failure straight back into the race.

### Round 9 — the 3-line close

Pass an explicitly-unusable snapshot instead of a bare `None`, so `record_fork` takes its
use-as-given path and the existing, already-tested `pre_existing is None` refuse-gate fires:

    fork_snapshot = {"parent_uuids": [], "parent_dir": "", "pre_existing": None, "parent_ct": None}

Plus the false docstring, and a test driving the real functions with `capture_fork_snapshot` raising.

On the hard stop: I said gap 2 would be dropped if refuted again. Applying a fully-specified 3-line
fix to an error branch — whose current failure mode is already safe, and where the reviewer refuted
the one structural concern — is not another redesign round, and shipping a known hole would be worse
than either option. This is the end of it either way.

### Round 9 result — LANDED. Gate: **931 tests, OK, `selfcheck ok`.**

`aitracker/term_vt.py:~1748-1772` — the snapshot is captured before `_fork_child`'s `execvp`, and the
`except` branch now passes an explicitly-unusable snapshot instead of a bare `None`, with the reason
spelled out in the comment: to `record_fork`, `None` means "self-capture", and a self-capture there
would run *after* the exec and swallow the child. `pre_existing: None` trips the already-tested
refuse-gate, so the fork stays honestly unresolved and is retried, then abandoned.

Both gaps complete.

## What shipped

**Gap 1 — the terminal accepts what a real terminal accepts.**
Modified keys per xterm's scheme (Ctrl/Shift/Alt/Meta on arrows, Home/End, the editing keypad),
F1-F12 (previously swallowed whole), Alt+Enter's newline-without-submit (previously submitted),
Ctrl+Space. Mouse press/drag/release/wheel forwarded in SGR or legacy encoding to any program that
asks, with Shift preserved as the native-selection escape hatch. `?1004` focus reporting.
Along the way, two bugs the mouse work exposed rather than caused: sends were unsequenced `fetch()`
calls, so **fast typing could already transpose characters**, and a release outside the pane left a
stuck drag.

**Gap 2 — a forked resume no longer loses the thread.**
The link is recorded at the only instant it is knowable, then resolved by two exact conditions: the
transcript was not present in a snapshot taken before the fork exec'd, and it carries the parent's
copied message `uuid`s. If neither holds, the tracker says nothing rather than guessing.

## What this cost, and what it bought

20 agents (all sonnet/haiku; no leg needed opus). Nine review rounds. The adversarial passes refuted
**seven** claims that the implementing agents — and in one case my own browser verification — had
reported as working:

| Refuted claim | How it was caught |
|---|---|
| motion/discrete sends are ordered | executed under Node: `RELEASE` arrived before the `MOTION` that preceded it |
| drag state always clears | release outside the pane left every later hover reporting as a drag |
| fork child identified correctly (round 1) | an unrelated same-cwd session claimed, permanently memoized |
| …(round 2) | a grandchild claimed by its grandparent, and by both ancestors at once |
| …(round 3) | `resolve_fork_child(B)` returned **A, B's own grandparent** |
| snapshot fails safely | a failed `os.listdir` silently disabled the gate and fell back to the old ambiguity |
| the pre-exec snapshot is always used | on the capture-failure branch it self-captured *after* the exec |

Three of those were "tests that cannot fail" — most memorably a regression test written for exactly
the bug it was blind to, because it used a 1000-second gap where the defect needed a sub-5-second
one. That is the lesson worth keeping from this task: **a test that passes against the broken code
is worse than no test**, and the only reliable way to know is to revert the fix and watch it go red.

## Next concrete step

Wait on the four investigation agents, then fan out implementation: one agent for the Python
`mouse_mode` plumbing, one for `keyToBytes`, one for the client mouse encoder, one for gap 2 once
its shape is decided.
