# PROJECT_STATUS — AI Session Tracker

*Orientation for someone helping position this work. Written by the person who built it.*

## 1. What it is / why it exists
A local web dashboard that shows, live, **what my AI coding sessions are actually doing** — across
tools (Claude Code, Auggie/Augment), refreshing every 2s. I run many concurrent agent sessions and
lost track of which were working, stuck, or waiting on me. Every tool already writes a session log to
disk; nothing surfaced it. This reads those logs (read-only, no network) and renders one uniform view:
a plain-language *Goal / Now / So-far* summary, todos, files touched, commands run, sub-agents,
background shells, PRs opened, and the assistant's own narration. Nothing leaves the machine.

The constraint that shaped everything: **zero dependencies, stdlib only, no build step.** It's a Python
package you can also bundle into a single standalone file. That forces every feature through the
standard library and keeps the whole thing auditable and trivially runnable.

## 2. Current state — working vs. in progress
**Working (in daily use):** the live dashboard end-to-end. Two providers (Claude Code, Auggie) both
feeding the same UI. Session sidebar with liveness/end-state badges (🤖 running, ⏳ waiting-on-answer,
✅ completed-last-run), pin/rename, mobile drawer + PWA install. Detail reader: summary, todos, files
(with diffs), commands (with output), sub-agents, background shells, narration (paginated, uncapped
history). A **PR panel** that reconstructs merged/closed state and attributes PRs opened by a session's
background agents — all from the session's own logs, no GitHub API call. Cross-source search. Optional
HTTP-Basic auth (constant-time, signed-cookie) for exposing it over a tunnel to a phone.

**In progress / rough edges:** only two providers wired; parser coverage tracks log-schema drift on the
vendors' side (Claude Code's JSONL format shifts, so `_tail_fields`-style heuristics need occasional
re-confirmation). PR state is inferred from logs, so it lags a merge that happened outside the session.

## 3. Key architectural decisions + tradeoffs
- **Provider seam, not per-tool forks.** Each tool is a `Provider` (`available/list/parse/search`);
  routes only ever call `all_sessions()`/`parse_any()`/`search_all()`. Adding a tool = one module +
  one line in `PROVIDERS`. Tradeoff: every capability must land on the *shared shape* both providers
  emit — more discipline per feature, but no capability exists in one tool and not the other.
- **Server owns policy; client only renders.** Thresholds, labels, ranking, liveness all computed
  server-side; the SPA never re-derives them. One liveness constant (`LIVE_WINDOW` = client `LIVE` =
  300s). Kills the classic bug where UI and backend disagree on "is this live."
- **Read-only w.r.t. logs; app state is atomic JSON.** flags/titles/pins/notes are the only things it
  writes, via atomic load/save, read live. Never mutates a tool's own logs.
- **Page baked at server startup** (SPA inlined from `web/*`), served `no-store`. Tradeoff: UI changes
  need a restart — but a plain browser reload always shows the current page, no stale-cache confusion.
- **Confirm the real log shape before parsing.** The #1 source of bad fixes here is guessing a schema;
  the rule is open an actual `~/.claude/*.jsonl` first. Parsers read a tail window for cheap liveness.

## 4. Tech stack / notable patterns
Pure Python stdlib (`http.server` `ThreadingHTTPServer`, `json`, `hmac`) + a hand-rolled vanilla-JS SPA
(no framework). Patterns worth naming: **id namespacing** for routing (`""` = Claude, `auggie:` prefix)
so one endpoint serves any source; **end-state inference** — detecting an unanswered `AskUserQuestion`
in the log tail to flag "waiting on you"; **failure-recovery discipline** — one broken provider can't
sink the list, and `BrokenPipeError`/`ConnectionResetError` guards everywhere because clients hang up
mid-poll every 2s; **remote parity** as a first-class seam (every feature must work over a tunnel/phone,
not just localhost). Verification gate: `make check` runs a self-check (**114 asserts**) plus a unit
suite (**~90 tests**) and must print `selfcheck ok`; a pre-commit hook blocks commits that fail it.

## 5. Demo-able / metric-worthy
- **Live demo:** run `make serve`, point at real concurrent Claude Code sessions, show the sidebar
  flip a session to ⏳ *waiting-on-answer* the instant it asks a question — that's the "aha."
- **Zero-dependency, single-file** distributable dashboard — no `pip install`, no build, `dist/tracker.py`.
- **Multi-tool via a ~2-function adapter:** "added Auggie support in one small module against a shared
  seam" is a clean design-story bullet.
- **~90 unit tests + a 114-assert self-check, gated at commit time** — demonstrates test discipline on a
  personal project, not just at work.
- Resume-bullet shape: *"Built a zero-dependency, real-time observability dashboard for AI coding agents
  — a provider-abstraction seam unifies multiple tools' session logs into one live view; server-authored
  policy, atomic local state, and a commit-gated 200+ assertion test suite."*

## 6. Open gaps / next steps
- More providers (Cursor, Codex, Gemini CLI) to prove the seam scales past two.
- PR state via an optional read-only GitHub check to close the "merged outside the session" lag.
- Schema-drift resilience: the vendor log formats change; a fixture-capture harness would catch breaks
  earlier than a user noticing a blank panel.
- Packaging polish (published `uv`/pipx install) if it's ever meant for anyone but me.
