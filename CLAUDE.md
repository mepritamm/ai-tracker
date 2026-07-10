# CLAUDE.md — ai-tracker

Agent context for this repo. Read before editing. Hard rules live in [`.claude/rules/conventions.md`](.claude/rules/conventions.md).

## What this is
A **single-file, zero-dependency** local web dashboard that shows what your AI coding sessions are doing — live, across tools. It reads the logs each tool already writes to disk and renders them. Nothing leaves the machine; no API keys, no network calls.

The whole app is **`tracker.py`** — a stdlib `http.server` backend **plus an embedded vanilla-JS SPA** (the `PAGE` string). There is intentionally no framework, no build step, and no package tree. "Copy one file and run it" is a feature, not an accident. **Do not split it up.**

## Commands
```bash
make serve            # start / cleanly restart on http://localhost:8787 (frees the port first)
make stop             # stop it
make check            # the mandatory gate: --selfcheck + the test_tracker.py suite (both green)
make test             # just the unit-test suite
make hooks            # install the pre-commit gate (blocks commits that fail `make check`)
python3 tracker.py --version | --help
```

## Architecture (the seams)
- **Providers.** Each AI tool plugs in as a `Provider` (`available/list/parse/search`). Registry: `PROVIDERS = [ClaudeProvider(), AuggieProvider()]`. The routes call the seam, not a source: `all_sessions()`, `parse_any(sid)`, `search_all(q)`. Ids are namespaced by prefix (`""` = Claude, `auggie:` = Auggie). **Add a tool = one adapter + one line in `PROVIDERS` + a `SRC` label** — no core changes.
- **Two shared shapes** every provider emits (so the client renders any source uniformly):
  - session-list dict: `{id, project, cwd, title, prompt, source, mtime}`
  - session-detail dict: `{meta, todos, files, reads, commands, commits, tests, requests, agents, agents_bg, shells, narrative, message, tokens, counts, overview, note, mtime, now}`
- **Server ↔ client.** Backend emits JSON; the SPA (`render`, `renderSide`, the modals) draws it. A capability spans **both** — add the field/route server-side *and* render it. Never re-derive server policy in JS.
- **Data sources (read-only):** Claude `~/.claude/projects/**/*.jsonl`; Auggie `~/.augment/sessions/*.json` (+ `task-storage` for todos). Cursor/Codex (SQLite) and Copilot (binary LMDB) have no adapter — they need format-specific readers.
- **App-owned state:** `flags.json`, `titles.json` via `_load_json`/`_save_json` — **read live** (no restart). Both are gitignored (personal).
- **Liveness:** one constant — `LIVE_WINDOW` (server) / `LIVE` (client) = 300s. Don't add a second threshold.

## The rule that bites everyone
**The `PAGE` (HTML/CSS/JS) is baked into the server at startup.** After editing `tracker.py` you **must restart** (`make serve`) to see UI/parse changes. Only `flags.json`/`titles.json` are read live. Tell the user which kind of change you made.

## Conventions
- Stdlib only. **No new dependencies. No build step. One file.**
- Land a capability at the **shared seam** so both providers inherit it — never two forked implementations (that *is* the next gap).
- Confirm a log's real shape (open an actual `~/.claude`/`~/.augment` file) **before** writing a parser — assumption is the top cause of bad fixes here.
- **Non-trivial logic ships a test** — an assertion in `_selfcheck()` and/or a case in `test_tracker.py`. `make check` (both) stays 100% green; it's enforced by a pre-commit hook (`make hooks`), so a failing gate blocks the commit.
- Atomic writes for on-disk state; keep the `BrokenPipeError`/`ConnectionResetError` guards (clients hang up mid-poll).
- **This file is edited by many sessions — re-read the region right before editing; never assume it matches an earlier read.**

## Skills (in `.claude/skills/`)
- `/tracker-gap` — add/uplift a capability at the shared seam.
- `/fix-flags` — resolve an issue the user 🚩-flagged in the app.

## Releasing
Open a PR against `main`. Maintainer publishing runs from a local, gitignored workflow — nothing to run from this repo.
