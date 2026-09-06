# Progress-spine time proportionality — Auggie CLI vs. Augment-ext (VSCode/Cursor)

## Verdict

- **Auggie CLI (`aitracker/providers/auggie.py`): already time-proportional, no change needed.**
  A reliable-enough join was already implemented (commit `62178a1`): `chatHistory`'s
  `add_tasks`/`update_tasks` tool calls echo a chat-side task id, and the matching
  `tool_result_node` text embeds that id alongside the task's own NAME (`_TASK_LINE_RE`).
  `parse_auggie` collects `name_to_ids` and `task_times` in its single existing pass and backfills
  each todo's `started_at`/`ended_at` by NORMALISED NAME when exactly one chat-side id matches
  (`todo_times_approximate("auggie")` marks it as approximate, not exact). Spot-checked against
  this machine's real `~/.augment/sessions/*.json`: 29 of 31 todos across the 20 most-recently
  modified sessions got real timings out of this join. This item was effectively already closed
  for Auggie CLI before this task; the remaining gap is Augment-ext.

- **Augment-ext (VSCode/Cursor extension, `aitracker/providers/augment_ext.py`): NO reliable join
  exists. Keeping the honest equal-width degradation (`started_at`/`ended_at` stay `None`).**

## What was examined

Opened real files under both `~/.augment/` (Auggie CLI's `task-storage/tasks/*`, used above) and
the VSCode/Cursor extension's per-workspace state (`~/Library/Application Support/{Code,Cursor}/
User/workspaceStorage/<hash>/Augment.vscode-augment/`, ~65 workspaces with Augment state on this
machine):

- `augment-kv-store/` — a LevelDB store. This is where the chat transcript (user/assistant turns,
  the closest thing to Auggie CLI's `chatHistory`) actually lives. It is binary and cannot be read
  stdlib-only (already documented in `augment_ext.py`'s module docstring) — so there is no
  chat-turn-level id space to join against AT ALL, unlike Auggie CLI where `chatHistory` exists as
  plain JSON and the barrier was only an id-space mismatch.
- `augment-user-assets/task-storage/tasks/<uuid>` — one JSON file per task, confirmed shape (both
  root "Current Task List" nodes and real leaf todos):
  ```json
  {"uuid": "...", "name": "...", "description": "...", "state": "COMPLETE",
   "subTasks": [...], "lastUpdated": 1758040446940, "lastUpdatedBy": "AGENT"}
  ```
  Exactly 7 keys, confirmed across dozens of real files (`Current Task List` chains and real named
  todos alike) — no `createdAt`, no start/end pair, no reference back to any conversation/turn id.
  `lastUpdated` is a single last-write instant, not a range.
- `augment-user-assets/agent-edits/shards/*` — per-file-edit checkpoints keyed by
  `<shard-uuid>:<abs-path>` with their own `metadata.lastModified`; already used for the `files`
  panel's timestamps. No task/todo id anywhere in a shard.

**Considered and rejected**: since each task file's own `lastUpdated` differs across sibling
leaf tasks in the same session (e.g. one real session's four leaf todos: `1758040446940`,
`1758040484037`, `1758040537310`, `1758041176041`), it's tempting to treat a task's own
`lastUpdated` as its `ended_at` and chain `started_at` from the previous sibling in `subTasks`
order. This was tested against every multi-child task node found on this machine (33 nodes with
2+ sub-tasks): **13 of 33 (~40%) have `subTasks` order that does NOT match ascending
`lastUpdated`** — i.e. the array order is not reliably chronological. Building a chain on that
assumption would silently show plausible-looking but WRONG segment widths in a large minority of
real sessions — exactly the "heuristic that will silently mislead" this task says not to invent.
There is also no guarantee `lastUpdated`'s bump always corresponds to a state-completing edit
rather than some other rewrite of the record.

## What would have to change upstream

Augment's VSCode/Cursor extension would need to either (a) expose its `augment-kv-store` chat
transcript in a stdlib-readable format (plain JSON/JSONL alongside or instead of LevelDB), or (b)
write a real start/end timestamp pair (not just `lastUpdated`) onto each task-storage file as it
transitions state, ideally alongside a stable ordering guarantee for `subTasks`. Absent either,
this provider has no reliable way to place todos on a real time axis, and the client's existing
equal-width fallback (`todo_times_approximate`, `started_at`/`ended_at` staying `None`) is the
honest answer — unchanged by this task.
