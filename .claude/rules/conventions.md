# Conventions — hard rules for editing ai-tracker

These are invariants, not suggestions. Breaking one is a regression even if the app still runs.

## Structure
1. **Package, not a scratchpad.** Sources live in `aitracker/` (Python) and `aitracker/web/` (the SPA). Edit those — never `dist/tracker.py`, which `make bundle` regenerates. Keep the module boundaries: providers under `providers/`, the shared seam in `registry.py`.
2. **Zero dependencies.** Standard library only. No `pip install`, no `requirements.txt`/`pyproject.toml`, no bundler, no build step.

## The shared seam (don't fork)
3. Every AI tool is a **`Provider`** (`available/list/parse/search`) in `PROVIDERS`. Routes call `all_sessions()` / `parse_any()` / `search_all()` — never a specific source.
4. A capability must hold for **every** provider. Land it on the **shared shape** (the list dict or the detail dict) or the shared renderer (`render`/`renderSide`), filled by **both** producers. Two parallel implementations of one capability is the next bug.
5. **Server owns policy; client renders it.** Add the field/route server-side *and* read it in the SPA. Never re-derive a server value (thresholds, labels, ranking) in JS. Liveness is one constant: `LIVE_WINDOW` (server) = `LIVE` (client) = 300s.

## Data & safety
6. **Read-only** w.r.t. session logs. No outbound network. App-writable state stays in `flags.json`/`titles.json` via `_load_json`/`_save_json` (atomic, read live).
7. **Confirm the real log shape** — open an actual `~/.claude/projects/*.jsonl` or `~/.augment/sessions/*.json` — before writing or changing a parser. Guessing a schema is the #1 cause of bad fixes here.
8. Keep the `BrokenPipeError`/`ConnectionResetError` guards — clients disconnect mid-poll every 2s.

## Verification
9. Non-trivial logic (a parser branch, ranking, a new panel) ships **one assertion in `_selfcheck()`**, covering both Claude and Auggie when the capability spans them.
10. `make check` must print **`selfcheck ok`** — never regress it.
11. **Restart to see UI/parse changes** (`make serve`) — the `PAGE` is baked at startup. Only the JSON data files are live. State which kind of change you made.

## Process
12. **Re-read the region right before editing** — this file is edited by multiple concurrent sessions and diverges. If an edit's match fails, the file moved; re-read.
13. Minimal diff, no drive-by refactors, no new deps. No commit/push unless asked — use `/tracker-push` (dual-remote license split), never a manual push.
