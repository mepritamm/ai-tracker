---
name: tracker-gap
description: Close a capability GAP in the ai-tracker app (tracker.py — a single stdlib http.server backend + an embedded vanilla-JS SPA) with ONE change landed at the SHARED SEAM so every path inherits it — never two forked implementations. The tracker's paths/asymmetries: (1) the SESSION-LIST shape produced by BOTH list_sessions() (Claude) and list_auggie() (Auggie), merged in /api/list — a per-session capability (title, source badge, live-ness, filter, search) must hold for both; (2) the SESSION-DETAIL result dict produced by BOTH parse_session() (Claude) and parse_auggie() (Auggie) — same keys (meta/todos/files/commands/narration/agents_bg/shells/overview/counts/note/mtime/now), so a detail capability lands on the shared shape + both producers; (3) the SERVER→CLIENT contract — a capability spans the parse/endpoint AND render()/renderSide() in the embedded PAGE, never hardcoded in one; (4) background AGENTS vs background SHELLS (parallel panels that usually move together); (5) LOCALHOST vs REMOTE (tunnel/phone/tablet) — a control the user merely records must work from a remote host, never be gated to localhost. MANDATORY on every capability: ships BOTH a behavioral eval (an assertion in the self-check / tests/test_selfcheck.py) AND unit tests in the tests/ suite for its distinct code paths + edge cases — covering both providers when it spans them — and keeps `make check` (selfcheck + unit tests) 100% green. Then RESTARTS the server and curls the endpoint to prove it end-to-end (the page is baked at startup — a UI change is invisible until restart). For ADDING or uplifting a capability in THIS repo — not fixing an issue the user 🚩-flagged in the app (that's /fix-flags). Local change only — no commit/push unless asked.
---

# Close a Capability Gap in the tracker — universally, across every path

You add (or uplift) a **capability** in **ai-tracker itself** — `tracker.py`, a single zero-dependency
Python file: a stdlib `http.server` backend that parses Claude Code / Auggie session logs, plus an
embedded vanilla-JS SPA (the `PAGE` string). A *gap* is a missing capability, not a broken behavior — so
this is a small **feature**, not a bug fix.

> Not `/fix-flags` (that resolves an issue the user raised with the 🚩 button in the app — a specific
> defect, minimal diff). Here you build a capability and make **every path** expose it. No PR gate, no
> Jira. Do **not** commit or push unless asked.

**Close the gap at the SHARED SEAM — once — so every path inherits it.** The tracker runs Claude and
Auggie sessions through parallel producers that emit the **same shapes**, and the browser renders those
shapes. A capability belongs on the shared shape (or the shared renderer), never duplicated per source or
split between server and client that then drift. The shared fix is almost always the *smaller* diff
**and** the only one that can't reopen on the path you forgot. Two parallel implementations *are* the
next gap.

## The paths (know them cold — the gap lives in the asymmetry)

- **Session list** — `/api/list` returns `list_sessions()` (Claude, top-N by mtime) **+** `list_auggie()`
  (Auggie conversations), merged and sorted. Every entry is the **same dict**:
  `{id, project, cwd, title, prompt, source, mtime}` (`source` ∈ `claude-desktop|cli|claude-vscode|auggie`;
  Auggie ids are prefixed `auggie:`). A per-session capability (a badge, the live filter, search ranking,
  rename) must work for **both producers** — land it on the shared dict, or on `renderSide()` which
  consumes it.
- **Session detail** — `/api/session?id=` dispatches to `parse_session(path)` (Claude) or
  `parse_auggie(uuid)` when the id starts `auggie:`. **Both return the same result dict** — keys:
  `meta, todos, files, reads, commands, commits, tests, requests, agents, agents_bg, shells, narrative,
  message, tokens, counts, overview, note, mtime, now`. A detail capability lands on that shape and is
  filled by **both** parsers (Auggie fills what it can — it has todos + meta only; Claude fills all).
  `render(d)` in `PAGE` consumes the shape.
- **Server → client** — the backend emits JSON; the SPA (`render`, `renderSide`, the modals) draws it.
  A capability spans **both** — add the field/endpoint server-side **and** render it. Never re-derive
  server policy in JS, never hardcode data the server should own.
- **Agents vs shells** — `agents_bg` (workflow/Task sub-agents under `<session-id>/**/agent-*.jsonl`) and
  `shells` (background bash) are **parallel** panels (`#bgpanel`/`#shpanel`, same `.bggrid`,
  live-first + "Show N finished" + completion toasts). A capability touching one almost always touches
  both — do them together.
- **Localhost vs remote (desktop/mobile/tablet)** — the SPA ships a phone block (`max-width:600px`) + a
  tablet master-detail block (`min-width:601px`/`max-width:900px`), with Sessions as a slide-in drawer on
  phones, and is reachable from a phone/tablet over a Cloudflare tunnel / Tailscale / LAN. **No control is
  gated by host** — do **not** add host/`location.hostname` gating (an old `.remote`-class that hid controls
  off-localhost was removed). The reasoning that once justified it ("🚩 flagging runs the AI locally, so
  it's pointless from a phone") was backwards: **anything the user merely records lands in the server's own
  JSON and is acted on locally later**, so it's exactly what you reach for on a phone. 🚩 flags queue to
  `flags.json` (where `/fix-flags` reads them on this machine); rename → `titles.json`; 📌 pin →
  `pins.json`; 📝 notes → `notes.json`. All of it must work from a *remote* host. Treat "is this
  local-only?" as **almost always no** for a user-data capability — the only genuinely local action is one
  that reaches out from the browser's own machine, which the tracker has none of. A capability with a
  button/input isn't done until it works in **all three** viewports — desktop, tablet, phone — served to a
  *remote* host, not just on localhost desktop. Verify by resizing to a mobile/tablet viewport, and (for a
  new control) grep the served page: no rule may hide it by host. (Two bugs this rule has already caught:
  📝-note entry hidden on mobile because it reused the hidden `.addflag` class; and 🚩 flagging itself
  hidden on the tunnel/phone by `.remote .addflag` — the whole flag-while-away workflow, gone. Both were
  the *same* mistake: gating recorded user-data on host.)

## Step 0 — Start in a worktree (mandatory)
**Never edit the primary checkout in place.** This repo is worked by multiple concurrent sessions sharing
one checkout, so an in-place edit interleaves with another session's WIP and forces a `git add -A` that
sweeps their unfinished work. Before touching a file: create a git worktree (EnterWorktree, based on local
HEAD — this repo has **no `origin` remote**, only `personal`), do **all** edits there, get `make check`
green **in the worktree**, and only then move to the main checkout / push to `personal`.

## Step 1 — Frame the gap (name the capability + find the asymmetry)
Before touching code, state in plain terms:
1. **The capability, in one line** — what the app should now do, over *all* in-scope sessions/panels
   (not one source, one session, one panel). Quote the source: the user's ask.
2. **The asymmetry** — does it exist for **Claude** sessions but not **Auggie**? On the **server** but not
   the **client** (or vice-versa)? For **agents** but not **shells**? On **localhost** but not a
   **remote** host — **desktop** but not **mobile/tablet** (unusable in the phone/tablet layout, or a
   control mistakenly gated to localhost)? Name which side has it and which lacks it. If it exists nowhere,
   you're adding it to the shared shape/renderer and lighting up all.
3. **The consumers it must reach** — the concrete server hook (a key on the session/result dict, a new
   `/api/*` route) **and** the concrete client hook (`renderSide` for list, `render` for detail, a
   modal). Write both down now; Step 3 wires both, Step 4 proves both.

## Step 2 — Build the capability ONCE, at the shared seam
Implement on the point every path already flows through, so all inherit it. Stdlib-only Python + vanilla
JS — **no new dependencies**, no build step, no framework. Keep it one file.
- **Pick the lowest shared seam that covers the capability:**
  - a per-session attribute (title, source, a flag, ranking input) → the dict built by **both**
    `list_sessions()` and `list_auggie()`; render in `renderSide()`. Confirm the JSONL/Auggie field
    against **real data before coding** — the #1 cause of bad fixes here (titles live in
    `aiTitle`/`customTitle`; background work lives under the `<session-id>/` subdir; Auggie sub-tasks are
    UUID refs; boilerplate — skill/tool lists, system-reminders — must be excluded from search).
  - a per-session-detail attribute (a new panel, a count, a summary line) → the **result dict** filled by
    **both** `parse_session()` and `parse_auggie()` (Auggie degrades gracefully — empty lists, a `note`);
    render in `render(d)`.
  - liveness / "is it active" → the single `LIVE_WINDOW` constant (server) and `LIVE` const (client) —
    one number, don't reintroduce a second threshold.
  - a new data view of a file/command/agent/shell → a focused `/api/*` route + a modal; reuse `mdBlock`
    (markdown) / `renderDiff` / the existing modal shell rather than a parallel one.
  - user-owned overrides (rename, flags, pins, notes) → the on-disk JSON (`titles.json`/`flags.json`/
    `pins.json`/`notes.json`) via the `_load_json`/`_save_json` helpers — these are **read live** (no
    restart) and, being recorded data, must **never** be gated to localhost (see the localhost-vs-remote path).
- **The anti-pattern that reopens the gap:** filling the field only in `parse_session` (Claude) and
  forgetting `parse_auggie`; or rendering it in `render` but never emitting it server-side; or adding a
  threshold/label in JS that duplicates a server value; or hiding a recorded-data control by host. If
  you're writing the feature twice, you found the seam you should have used once. Collapse to it.
- **Broader, not speculative.** Generalize to the seam the capability needs — nothing wider. No new
  endpoint/config/abstraction for a path the gap never touches; the universal fix is the *smaller* diff.
- **Preserve the guarantees:** read-only w.r.t. session logs, no outbound network, no new dependency,
  writable state stays in the app's own JSON files, and the server keeps tolerating client disconnects
  (the `BrokenPipeError` guards).

## Step 3 — Wire EVERY consumer (a capability only one path can reach is half-built)
- **List capability:** emitted by both `list_sessions()` **and** `list_auggie()`, and drawn in
  `renderSide()` (and respected by search/live-filter if relevant).
- **Detail capability:** filled by both `parse_session()` **and** `parse_auggie()`, and drawn in
  `render(d)` — verify the Auggie branch degrades cleanly (no `undefined`, no JS throw on empty lists).
- **Agents/shells capability:** apply to **both** panels.
- **Localhost & remote:** a control the user records (a button/input feeding the app's own JSON) works on
  localhost desktop **and** from a remote host on phone/tablet — no host gating, usable in every viewport.
- **Server ↔ client:** the JSON key the server adds is the key the client reads — same name, no
  re-derivation.

## Step 4 — MANDATORY: ship evals AND unit tests, then prove it end-to-end
**Every capability lands with BOTH an eval and unit tests — this is not optional.** A capability without
them is unfinished, no matter how well it runs by hand. Land them in the same change:

1. **Eval (behavioral assertion that fails if the logic breaks).**
   - *Parser / data-shape logic* → an assertion in the built-in self-check
     (`_selfcheck()` / `tests/test_selfcheck.py`), mirroring the fixture style: build a temp JSONL / temp
     `~/.augment` dir, call the parser/lister, assert the shape. Cover **both** the Claude and Auggie paths
     when the capability spans them.
   - *Server / endpoint / UI logic* → an eval in the integration suite (`tests/test_integration.py`) that
     boots the real server (ephemeral port) or builds the page and asserts the observable behavior
     (including, for a user-data control, that the served page does **not** gate it by host).
2. **Unit tests for the distinct paths + edge cases.** One assertion is a floor, not the target — test what
   can regress silently: the happy path **and** the branches (missing/empty input, the off/default state,
   malformed input, the security/auth path, both providers). New route, new config/env, new panel, new
   parser branch → each gets its own test.
3. **`make check` must print `selfcheck ok` with every test green** (`python3 -m aitracker --selfcheck` +
   the `tests/` suite; `python3 tracker.py --selfcheck` in single-file layout). **Never regress it.**
4. **Restart the server** (`make serve`, or kill the `:8787` listener and relaunch) — the page is baked in
   at startup, so a client change won't show otherwise.
5. **Prove it live:** `curl` the relevant endpoint (`/api/list`, `/api/session?id=…`, `/api/search?q=…`)
   and confirm the new field/behavior in the JSON, for **both** a Claude and an Auggie session where the
   capability spans them. For a pure UI change, `curl /` and grep the served page for the new markup/JS.
6. **Report** per path: the capability, the seam it landed on, and the proof — the **new eval + test
   names** plus the curl/browser output.

## Rules
- Confirm the data shape from **real** session files before changing any parser — assumption is the #1
  cause of bad fixes here.
- One stdlib file, no new deps, no build step. Atomic writes for on-disk state. Don't regress
  `--selfcheck`.
- **Evals + unit tests are mandatory, not optional.** Every capability ships with (a) a behavioral eval
  pinning it (self-check for parser/data, integration test for server/UI) **and** (b) unit tests for its
  distinct paths and edge cases — covering both providers when it spans them. `make check` stays 100%
  green. Code without both is incomplete work — do not report a capability as done until they exist and pass.
- **No host gating for recorded user-data.** Flags/rename/pin/notes (anything landing in the app's JSON)
  must work from a remote host on every viewport — never gate a control by `location.hostname`.
- **Restart to see UI/parse changes.** Only the JSON data files (`flags.json`/`titles.json`/`pins.json`/
  `notes.json`) are read live. Say which kind of change you made so the user knows whether to reload or restart.
- **This file is edited by multiple sessions.** Re-read the region right before editing; never assume it
  matches an earlier read. If a match fails, the file diverged — re-read.
- **Worktree discipline (mandatory).** Every edit happens in a git worktree, is validated there (`make
  check` green), and only then moves to the main checkout — never in-place on the primary checkout. Base
  the worktree on local HEAD (no `origin` remote here). This is what keeps concurrent sessions from
  clobbering each other. See Step 0.
- If the gap needs a product decision (two reasonable behaviors) or data that isn't on disk (e.g. Auggie's
  cloud transcript), **ask** or ship the honest local-only version with a `note`, rather than guessing.
- Local change only — no commit, push, or PR unless the user asks.
