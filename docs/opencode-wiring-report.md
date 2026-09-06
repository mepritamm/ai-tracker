# opencode wiring report (anomalyco/opencode)

Research target: `github.com/anomalyco/opencode`, branch `dev` (v1.18.18, binary `lildax`).
Purpose: mirror opencode's wiring so ai-tracker's dashboard can surface/read its sessions the way it reads Claude Code sessions.

All URLs follow the pattern `https://raw.githubusercontent.com/anomalyco/opencode/dev/<path>` unless noted.

---

## Q1 — Config file: name, location, schema

### File name
Two names are pinned, in this exact array (`src/config.ts`, L142):

```ts
["opencode.json", "opencode.jsonc"]
```

Both extensions are parsed with `allowTrailingComma: true` and the same decode options:

```ts
decodeOptions = { errors: "all", onExcessProperty: "ignore", propertyOrder: "original" }
```

### Discovery / precedence
Configs are discovered by walking upward from the working directory to the project root (nearest wins):

```ts
fs.up({ targets: [".opencode", ...names.toReversed()],
        start: location.directory,
        stop: location.project.directory })
```

- Global config lives in the global directory (`discovered = []`).
- The config entry is resolved from `@opencode-ai/tui/config` in `cmd/run/runtime.boot.ts`.
- A v1 → v2 migration is applied via `ConfigMigrateV1`.
- Configs are cached per location on disk.

Source: `src/config.ts` (227 lines).

### Docs location
There is **no root `docs/`** in the opencode repo. Web docs are `.mdx` files under `packages/web/src/content/docs/` (root + 16 locale directories). The repo-side config reference is:

- `specs/v2/config.md` (399 lines)

Its "Review Order" lists these config groups:

1. File Metadata
2. Process And Server Settings
3. Providers And Model Selection
4. Commands And Project Resources
5. Plugins
6. Filesystem And Tool Runtime
7. Sharing And Identity
8. Agents And Permissions
9. Integrations
10. Conversation Lifecycle
11. Deprecated And Experimental Settings

### v2 schema — field status digest (per field)
| Field | Status in v2 | Notes |
|---|---|---|
| `$schema` | keep | read-only metadata; loader must not insert it or create files for it |
| `command` | remove | → workflows/skills |
| `skills` | redesign | single array of local path / remote URL discovery sources |
| `reference` | remove | → plural `references` |
| `references` | new | plural, array of local paths/glob patterns/remote URLs |
| `instructions` | keep | array of local paths/glob patterns/remote URLs |
| `plugin` | remove | → plural `plugins` |
| `plugins` | new | ordered loading of package strings or `{ package, options? }`; local plugin code only from plugin dirs (e.g. `.opencode/plugins/`); no configured local paths/file URLs |
| `formatter` | keep | singular |
| `lsp` | keep | `boolean \| Record<string, entry>`; custom servers need `command` + `extensions` |
| `attachment` | remove | → plural `attachments` |
| `attachments` | new | `{ image?: { auto_resize?, max_width?, max_height?, max_base64_bytes? } }` |
| `tool_output` | keep | `{ max_lines?, max_bytes? }` |
| `share` | keep | `"disabled"` in the share/enterprise region |
| `enterprise` | keep | `{ url }` |
| `username` | keep | share/enterprise region |
| `provider` | remove | → plural `providers` (no singular alias) |
| `providers` | new | ordered; options are partial patches merged in config order; `env` = additive credential env-name list |
| `disabled_providers` / `enabled_providers` | remove | → `experimental.policies` + ordered `provider.use` allow/deny with wildcards |
| `model` | keep | fallback when session/agent unspecified |
| `small_model` | remove | use agent `title` model override |
| `default_agent` | remove | |
| `mode` | remove | |
| `agent` | remove | → plural `agents` |
| `permission` | remove | → plural `permissions` |
| `permissions` | new | ordered `{ action, resource, effect }`; retains `"ask"`; reusable inside `agents` |
| `tools` | remove | legacy boolean map |
| `mcp` | redesign | explicit servers; shape `servers.<name>.{ type: "local"\|"remote", command[], environment{}, disabled, timeout{startup\|request}, url, headers, oauth{client_id, client_secret, scope, callback_port, redirect_uri} }` |
| `compaction` | redesign | `{ auto?, prune?, keep: { tokens }, buffer }`; `keep.tokens` = recent-history token budget, `buffer` = headroom before auto-compaction; example `{ auto: true, prune: true, keep: { tokens: 2000 }, buffer: 10000 }` |
| `layout` | remove | |
| `experimental.disable_paste_summary` | remove | |
| `experimental.batch_tool` | remove | |
| `experimental.openTelemetry` | remove | |
| `experimental.primary_tools` | remove | |
| `experimental.continue_loop_on_deny` | remove | |
| `experimental.mcp_timeout` | remove | → default `mcp.timeout.request` + per-server `mcp.servers.<name>.timeout.request` override |
| `mcp_timeout` | remove | → `mcp.timeout.request` |

Config groups and policies evaluated in reverse document order (see `specs/v2/config.md` Review Order + the provider-policy doc).

---

## Q2 — Hooks: availability and format

**No hooks. Not in v1, not in v2.**

- `"hook"` greps across the source tree matched only dev-dependency noise (`@octokit/webhooks-types`, `@opentelemetry/context-async-hooks`).
- `specs/v2/config.md` ported no `command`-style or hook fields.
- Plugin events are the only extensibility mechanism opencode exposes for reacting to lifecycle/behavior.

If ai-tracker needs opencode event reactions, the integration surface is **plugins**, not hooks.

---

## Q3 — Session/transcript storage: location, format, fields

### Tables
`packages/opencode/src/storage/schema.ts` re-exports the core tables from `@opencode-ai/core/session/sql`.

- **SessionTable** owns: `cost`, token `input`/`output`/`reasoning`/`cache_read`/`cache_write`, `metadata`, `revert`, `permission`, `agent`, `model`, `time_compacting`, `time_archived` — plus indexes `session_project_idx` / `session_workspace_idx` / `session_parent_idx`.
- **Message**, **Part**, **Todo**, **SessionMessage** tables round out the transcript model.
- **SessionInputTable** and **SessionContextEpochTable** are defined at `session/sql.ts` L141–176 (`sql.ts` is 176 lines; `store.ts` is 63 lines).

### Storage paths (evidence files)
- `tool-output/db_paths.txt` — database location(s).
- `tool-output/session_paths.txt` — session storage location(s).

---

## Q4 — Non-interactive list/read CLI

**⚠ Docs-vs-source discrepancy — flag for the tracker integration.**

- Docs advertise `opencode list`, `opencode read`, and a `--print-last-message` style capability.
- The actual source command inventory (77 entries, `cli_cmd_all.txt`) has only:
  - `session list`
  - `session delete`
- `session list` has **no** last-message / transcript-print flag.
- Relevant implementations:
  - `cmd/session.ts` (147 lines) — `session list`/`session delete`, table + JSON output formats.
  - `cmd/stats.ts` (393 lines) — stats flags/semantics.
  - `cmd/serve.ts` — server surface.

Treat the docs as aspirational; the shipped CLI is `session list` / `session delete`.

---

## Sources (evidence files under tool-output)
- `src/config.ts` (227 lines) — Q1 names/layer/parsing/priorities.
- `specs/v2-config.md` (399 lines) — Q1 schema reference.
- `cmd/session.ts`, `cmd/stats.ts`, `cmd/serve.ts`, `cmd/run/runtime.boot.ts` — Q4 CLI + config entry.
- `storage/schema.ts`, `session/sql.ts`, `session/store.ts` — Q3 schema/format.
- `config/` — 21 `ConfigV2.*` sources (no hooks anywhere).
- `opencode-pkg/` — package.json/postinstall/build facts.
- `cli_cmd_all.txt` — 77-entry command inventory.
- `root_tree_e23586af.json` — verified 7,274-entry recursive tree.
- `db_paths.txt`, `session_paths.txt` — storage path evidence.

---

## Addendum — confirmed against the live database

All facts below were verified on this machine after the main report was written:

- **Database path and state:** `~/.local/share/opencode/opencode.db` (43MB, WAL mode), with adjacent `opencode.db-wal` and `opencode.db-shm` files. Env override: `TRACKER_OPENCODE_DB`.
- **Live contents at time of writing:** 77 sessions, 2000 messages, 5338 parts, 13 todos, 3 projects.
- **Tables present:** account, account_state, control_account, credential, data_migration, event, event_sequence, message, migration, part, permission, project, project_directory, session, session_context_epoch, session_input, session_message, session_share, todo, workspace.
- **Read-only access:** The tracker opens the database via `sqlite3.connect("file:<path>?mode=ro", uri=True)`; write attempts raise `OperationalError`. The `account` and `credential` tables contain live access/refresh tokens and are never read by the tracker.
- **Data encoding:** Timestamps are epoch milliseconds; `session.model` is a JSON string; text parts flagged `"synthetic": true` are system-reminder boilerplate and are excluded from prompts/narration.
- **CLI resolution:** Q4's docs-vs-source discrepancy is moot for this integration — the tracker reads the database directly and never shells out to the `opencode` CLI.
