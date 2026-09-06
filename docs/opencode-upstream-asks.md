# Opencode Store Upstream Asks

This document lists capabilities the opencode local store currently does not expose, preventing external dashboards (specifically ai-tracker) from showing feature parity with what is displayed for other AI coding tools. It is written for opencode maintainers who work on the store schema and CLI. Each ask is actionable and grounded in how an external read-only viewer would consume the data.

## What We Read, and How

ai-tracker reads the opencode SQLite store at `~/.local/share/opencode/opencode.db` with `mode=ro` (read-only). It reads from:

- `session` table (id, slug, title, directory, agent, model, time_created, time_updated, cost, token counts, summary edits)
- `message` table (role, agent, model, timestamps, parentID for sub-agent lineage, path, cost, token counts, finish status)
- `part` table (type, text, tool, state, and nested timestamps)
- `todo` table (content, status, priority, timestamps)
- Tool output from disk cache at `tool-output/<callID>`

ai-tracker **deliberately never reads** `account` or `credential` tables, which hold live access and refresh tokens. This read-only, live-dashboard architecture is the design assumption throughout.

## What Opencode Already Does Well

Opencode's store is well-structured for external consumption:

- **Session and message metadata** are comprehensive (id, title, directory, agent, model with providerID/modelID/variant, precise epoch-ms timestamps).
- **Per-message token accounting** is granular (input, output, reasoning, cache_read, cache_write) and accurate.
- **Sub-agent tracking** via `message.parentID` and child session references shows agent lineage clearly.
- **Todo management** records real per-row timestamps, allowing viewers to show precise "created" and "updated" moments. This is more precise than Claude Code, where viewers must approximate by name-matching. This is a genuine strength.
- **Session-level edit summary** (files added/deleted/changed) is accessible at `session.summary_*` columns.

## Asks (by value to an external viewer)

### 1. Context-Window Size Not Recorded

**What's missing:** Neither `session` nor `message` records the effective context limit of the model in use.

**Why it matters:** An external viewer can display "1.2M tokens used" but cannot show the human-readable signal "62% of context window full." For a session running for hours with accumulating tokens, this is the single most useful metric to decide whether to intervene or let it continue. Currently, viewers must hard-code model context limits externally.

**Suggested minimal shape:** Add `context_limit` (integer, tokens) to `message` table, or once per `session` if it does not vary. If `model.contextWindow` exists elsewhere in the model registry, reference it; otherwise, populate it at message creation time.

### 2. Awaiting User Input Not Flagged

**What's missing:** No record of when the agent is blocked waiting for user input or responding to a question.

**Why it matters:** On a multi-session dashboard, the highest-value alert is "this session needs you now." Without a flag, an external viewer must poll the terminal or re-parse recent messages to infer "agent is waiting." This is expensive and unreliable.

**Suggested minimal shape:** Add a boolean or enum column `awaiting_input` to `session`, and optionally a `prompt_text` column to store the question. Set it when an agent prompts; clear it on the next user message.

### 3. Structured File-Edit Record Missing

**What's missing:** `session.summary_*` gives aggregate counts (files, additions, deletions), but there is no per-file edit list.

**Why it matters:** An external viewer cannot answer "which files did this session touch, in what order?" without parsing `part.state.input` for every tool call, which couples the viewer to each tool's (tool-specific) argument schema. This is brittle and expensive.

**Suggested minimal shape:** A `file_edit` table with (session_id, file_path, operation, first_touch_timestamp, last_touch_timestamp, edit_count). Populate it as tool calls complete.

### 4. Git Branch Not Captured

**What's missing:** `session.directory` records the project path but not the active git branch.

**Why it matters:** An external viewer cannot surface "this session was working on feature/x-123." For a user tracking work across multiple branches in parallel, this is necessary context. Claude Code records this as `gitBranch` per entry.

**Suggested minimal shape:** Add `git_branch` to `session` table, populated at session creation or on first git command. Update it if a branch change is detected during the session.

### 5. Opencode Version Not Stamped

**What's missing:** `session.metadata` is NULL in practice. A viewer cannot determine which opencode build produced a transcript.

**Why it matters:** When the schema or behavior changes, viewers need to know which version they are reading. Otherwise, schema shifts cause silent misinterpretation.

**Suggested minimal shape:** Populate `session.metadata` with a JSON object containing at minimum `{"opencode_version": "X.Y.Z"}` at session creation.

### 6. Session Path Column Unused

**What's missing:** `session.path` is always NULL and does not appear to be used.

**Why it matters:** A viewer may assume it contains actionable data. If the column is dead code, documenting it as deprecated prevents wasted integration effort.

**Suggested minimal shape:** Either populate `session.path` with the absolute project path (or drop it). If you drop it, note it in the schema changelog.

### 7. Session Message Bridge Table Empty

**What's missing:** The `session_message` table exists but contains zero rows; all data lives in `message` + `part`.

**Why it matters:** A viewer might target the wrong table, leading to silently empty results. If it is superseded schema, marking it as deprecated or removing it prevents misdirected queries.

**Suggested minimal shape:** Either drop `session_message`, or document it in the schema as deprecated. If there is a reason to keep it for backward compatibility, populate it explicitly.

### 8. Non-Interactive CLI Is Thin

**What's missing:** The documented CLI includes commands like `opencode read` and `--print-last-message` that do not exist in the command inventory.

**Why it matters:** Users and integrators following the docs cannot execute them. ai-tracker works around this by reading the database directly and never shells out, but the discrepancy is friction.

**Suggested action:** Either ship the documented read commands or correct the CLI documentation to match the actual inventory.

### 9. PR and Remote-Work Linkage Missing

**What's missing:** No record of pull requests opened or git pushes made during a session.

**Why it matters:** An external viewer could surface "this session opened PR #123" as a high-value summary point. This is nice-to-have, not critical.

**Suggested minimal shape:** Optionally, capture PR URLs or commit SHAs seen in tool output and store them in a new `pr_record` or `remote_work` table, or as a JSON array in `session.metadata`.

## Not Asks (Deliberate Design Differences)

**Background shells:** opencode does not maintain a background shell concept; all bash calls are synchronous with inline output. This is a design choice. ai-tracker intentionally renders an empty shells panel for opencode sessions, matching the model.

**None of the above asks imply opencode is insufficient.** They are gaps specific to external dashboard consumption. ai-tracker already works with the current schema by reading it directly; these asks would simply reduce the viewer's coupling to opencode's internals and unlock richer cross-tool features.
