# A5 — `fail_cmd` on the session-list dict

## Task
Wire the control-room board's "failing" tile state (`s.fail_cmd`, client already reads
it — `ext_cr_board.js`'s `sessionState()`) to a real signal, WITHOUT adding a per-session
full-file parse or any O(file size) work to the cheap list path (`list_sessions()` /
`list_auggie()` / `_list()`, called every ~2s poll across ~950 sessions).

## Investigated

- **overview.py** — builds a single aggregate "what's happening right now across all
  sessions" summary, not a per-session cache the list path could look up. No help.
- **App-owned state (`flags.json`/`titles.json`)** — user-authored (pins, flags, titles),
  never carries pass/fail signal. No help.
- **Does the list path already touch each file's bytes for something else?**
  - **Claude** (`providers/claude.py`): yes. `_session_meta()` → `_tail_scan()` already
    reads the **last 96KB** of every session file on every poll (cached by mtime,
    so an unchanged file costs nothing on repeat) to derive `waiting`/`ended`/
    `last_text`/`model` for the list dict. Opened a real transcript
    (`~/.claude/projects/*/*.jsonl`) and confirmed the exact shape: an assistant
    `tool_use` block with `name:"Bash"` carries `id` + `input.command`; the matching
    user-role `tool_result` block carries `tool_use_id` + a boolean `is_error` —
    the SAME join `parse_session()`'s `errors_by_id` does over the whole file
    (`providers/claude.py` ~line 1077), just narrower. Confirmed against a real
    session with an errored Bash call
    (`.../VIDA20-dw-vida-stack/ba87da7f-....jsonl`, `tool_use_id
    toolu_01M2984CDHxvjZjm6XG7o6ac`, `is_error:true`).
  - **Auggie** (`providers/auggie.py`): even better — `list_auggie()`'s cache-miss
    path already `json.load()`s the **entire** session file into memory (comment at
    `_auggie_last_narration`: "unlike Claude, which only tails"), cached by mtime in
    `_AUGGIE_LIST_CACHE`. Opened a real `~/.augment/sessions/*.json` and confirmed:
    `launch-process` tool_use (`tool_name`, `tool_use_id`, `input_json.command`) in
    one exchange's `response_nodes`, its result as a `tool_result_node` with
    `is_error` in a **later** exchange's `request_nodes` (Auggie files results under
    the next exchange, per the module's existing `errors_by_id` comment). Since the
    whole file is already resident, deriving this costs zero extra I/O.
  - **Augment ext** (`providers/augment_ext.py`, VSCode/Cursor): no — this provider's
    chat transcript lives in the extension's LevelDB kv-store, unreadable
    stdlib-only (documented in the module's own docstring). It has no command/tool
    stream at all (`"model": ""` is already honestly unknown for the same reason).
    No cheap signal, no expensive one either — nothing to source.
- **Filesystem-level signal**: none exists (no sidecar exit-code file, no separate
  status marker on disk for either tool).

## Decision — Branch (A): cheap signal exists (for Claude + Auggie)

Implemented `fail_cmd` (string | null) on the session-list dict, sourced entirely from
data each provider's list path **already reads** for other fields:

- `providers/claude.py`: `_tail_scan()` now also tracks Bash `tool_use` ids → command
  text (truncated to 60 chars) seen in the same 96KB tail window, and on a matching
  `tool_result`, sets `fail_cmd` to that command if `is_error`, else clears it to
  `None` — "latest Bash result in the tail wins," the same rule already used for
  `model`/`last_text`. Threaded through `_session_meta()` → `list_sessions()`.
- `providers/auggie.py`: new `_auggie_fail_cmd(chat)` helper, same latest-wins join
  over `launch-process` tool_use/`tool_result_node.is_error`, run against the chat
  history `list_auggie()` already has in memory. Cached alongside `model`/`last_text`
  in `_AUGGIE_LIST_CACHE`.
- `providers/augment_ext.py`: emits `"fail_cmd": None` explicitly — honest absence,
  same pattern as its existing `"model": ""`.
- `registry.py`: `all_sessions()`'s shared per-session loop (where `pinned`/
  `open_flags`/`continued_as` etc. are stamped onto every provider's dict) now also
  does `s.setdefault("fail_cmd", None)` — belt-and-suspenders so the key is
  guaranteed present for every session regardless of provider, matching the
  "never omit the key" requirement even if a provider forgot to set it.

Only Bash/`launch-process` (i.e. real shell commands) count, matching
`parse_session()`'s existing `counts.errors` semantics — not just the `test`-kind
subset (`counts.tests_failed`), matching the JS doc-comment's "a command/test
returned non-zero."

### Measured: `all_sessions()` timing, before vs. after, real corpus (957 sessions)

Compared a clean-baseline copy of `aitracker/` (the 4 edited files checked out at
`HEAD`, everything else identical) against the patched worktree, same machine, same
session corpus, warm filesystem cache:

| | cold | warm (repeat) |
|---|---|---|
| BASELINE (`HEAD`) | 1.363s | 0.110s / 0.090s |
| PATCHED (this change) | 0.917s | 0.107s / 0.092s |

No measurable regression — warm-path numbers are within normal run-to-run noise (the
patched cold run was actually faster, plain filesystem-cache variance, not a real
effect). This matches the investigation: no new file reads were added anywhere: the
signal rides the *existing* 96KB-tail read (Claude) or the *existing* full in-memory
load (Auggie), both already paid for by `model`/`last_text`/`waiting`/`ended`.

`fail_cmd` was non-null on 116/957 real sessions after the change, confirming the
signal actually fires (example: a `printf` Bash call flagged `is_error` in a live
session's tail).

### Verify
`python3 -c "import aitracker"` → succeeded, no errors.

## Note for Augment ext (the one provider left on branch B)

If a future implementer wants `fail_cmd` for the VSCode/Cursor extension provider too,
the cheapest place would be **not** the LevelDB chat store (unreadable stdlib-only,
per the module docstring) but the **agent-edit shard files** the list path already
scans in `_files_touched()`/`_iter_tasks()` — check whether a shard or the task-storage
file's own JSON ever records a run/build/tool exit status alongside `state`/
`lastUpdated` (unconfirmed either way; wasn't checked in depth since this provider has
no command stream to key off in the first place, distinctness from Claude/Auggie noted
above). Absent that, this provider simply has no cheap failure signal and `fail_cmd:
None` is the honest, permanent answer — same class of gap as its already-honest
`model: ""`.
