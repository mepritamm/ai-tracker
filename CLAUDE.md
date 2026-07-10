# CLAUDE.md — ai-tracker

Agent context. Read before editing. Hard rules: [`.claude/rules/conventions.md`](.claude/rules/conventions.md).

## What this is
A **zero-dependency** local web dashboard showing what your AI coding sessions are doing — live, across tools (Claude Code, Auggie, …). It only **reads** the logs each tool writes to disk; nothing leaves the machine.

## Layout (production package; still stdlib-only)
```
aitracker/            the Python package
  cli.py server.py page.py registry.py store.py overview.py util.py config.py
  providers/base.py providers/claude.py providers/auggie.py
  web/index.html app.css app.js        the SPA as real files (inlined at serve time by page.py)
tests/test_selfcheck.py                 the self-check, as stdlib unittest
scripts/bundle.py                       make bundle -> dist/tracker.py (standalone single file)
pyproject.toml  Makefile  README.md
```
Run from a clone via `python -m aitracker`, or install with `uv` → the `ai-tracker` command.

## Commands
```bash
make serve            # start / restart on http://localhost:8787 (frees the port first)
make stop
make check            # the gate: python -m unittest discover -s tests  → prints "selfcheck ok"
make bundle           # regenerate the standalone dist/tracker.py
python -m aitracker --version | --help | --selfcheck
```

## Architecture (the seams)
- **Providers.** Each tool is a `Provider` (`available/list/parse/search`) in `aitracker/providers/`. Registry (`registry.py`): `PROVIDERS`, `all_sessions()`, `parse_any(sid)`, `search_all(q)`. Routes call the seam, never a source. Ids namespaced by prefix (`""`=Claude, `auggie:`). **Add a tool = one module in `providers/` + one line in `PROVIDERS` + a `SRC` label in `web/app.js`.**
- **Shared shapes** both providers emit: the session-list dict and the session-detail dict (`meta/todos/files/commands/narration/agents_bg/shells/overview/counts/…`). The SPA renders any source uniformly.
- **Overridable paths are late-bound via `config.NAME`** (so tests and callers see one source of truth). `store.py`/`providers/*` reference `config.FLAGS_FILE` etc., not a copied import.
- **App-owned state:** `flags.json`/`titles.json` via `store._load_json`/`_save_json` — read **live**. Both gitignored.
- **Liveness:** one constant — `LIVE_WINDOW` (config) = `LIVE` (web/app.js) = 300s.

## The rule that bites everyone
The page is assembled from `web/*` **at server startup** (`page.build_page`). After editing `aitracker/**` or `web/**` you **must restart** (`make serve`). Only `flags.json`/`titles.json` are read live.

## Conventions
- **Stdlib only, no new dependencies.** No build step for running (the `web/` inline is at serve time; `make bundle` is optional packaging).
- Land a capability at the **shared seam** so every provider inherits it — never two forked implementations.
- Confirm a log's real shape (open an actual `~/.claude`/`~/.augment` file) **before** writing a parser.
- Non-trivial logic ships an assertion in `tests/`; `make check` stays green.
- **Edit the sources (`aitracker/`, `web/`), never `dist/tracker.py`** — it's generated. Re-read a region before editing (multiple sessions touch this repo).

## Skills (`.claude/skills/`)
`/tracker-gap` (add a capability at the seam), `/fix-flags` (resolve a 🚩), `/tracker-push` (PR to both remotes, license-split).
