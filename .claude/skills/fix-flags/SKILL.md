---
name: fix-flags
description: Debug and fix issues the user raised live via the 🚩 Flag button in the Claude Code session tracker app (tracker.py). Use when the user says "fix the flags", "resolve the open flags", "debug my flags", or after they flag an issue/gap in the tracker UI.
---

# Fix tracker flags

Resolve the open issues the user raised with the 🚩 Flag button in the session tracker. Flags live in `flags.json` at the repo root; each is `{id, session, project, note, context, ts, resolved}`. The fix is almost always in the `aitracker/` package or in how it parses `~/.claude/projects/*/*.jsonl`.

## Workflow

1. **List open flags.** Run the helper from the project root:
   ```
   python3 .claude/skills/fix-flags/resolve.py list
   ```
   Each flag's `note` is the issue; `context` is what Claude was doing when it was raised (a hint, not gospel).

2. **For each open flag, in order:**
   a. **Understand** the note. Restate the concrete ask in one line. If it bundles a bug *and* a feature, handle both.
   b. **Investigate against real data first — never guess the JSONL schema.** Inspect actual session files (`~/.claude/projects/*/*.jsonl`) and background-agent transcripts (`<session-id>/**/agent-*.jsonl`) to confirm field names, shapes, and where data lives before editing parser logic. Prior flags were caused by exactly this: titles in `aiTitle`/`customTitle`, background work under the session subdir, liveness from file mtime.
   c. **Fix** in `aitracker/` (the right module/provider). Match the existing style; stdlib only, no new dependencies unless the user opts in. Prefer the smallest change that holds.
   d. **Verify.** Run `make check`. Extend the self-check with one assertion covering the fixed behaviour. For UI/CSS changes, also boot the server (`PORT=88xx python3 -m aitracker &`) and `curl` the relevant endpoint or page to confirm.
   e. **Resolve** only after it verifies:
      ```
      python3 .claude/skills/fix-flags/resolve.py resolve <id>
      ```

3. **Report** per flag: the ask, the root cause, the fix (file:line), and the verification result.

## Rules

- Confirm the data schema from real files before changing parsing — assumption is the #1 cause of bad fixes here.
- One stdlib file, no new deps, atomic writes for any on-disk state. Don't regress the self-check.
- **Live changes vs restart:** data files (`flags.json`, `titles.json`) are read per-request, so they refresh without a restart. Anything in `tracker.py` itself — including the served HTML/CSS in the `PAGE` string — needs the user to restart `python3 -m aitracker`. Always tell the user which kind of change you made.
- If a flag needs a product decision (which of two behaviours?) or external access that isn't available (e.g. `claude` CLI auth, a locked datastore), **don't guess** — ask, or leave it open with a one-line note explaining why and what's needed.
- Never delete flags; only resolve. If a flag is already addressed by earlier work, resolve it and say so.
- If `resolve.py` can't find `flags.json`, pass it explicitly: `FLAGS_FILE=/path/to/flags.json python3 .claude/skills/fix-flags/resolve.py list`.
