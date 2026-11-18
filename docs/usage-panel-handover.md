# Handover — Config → Usage panel and account registration (OpenRouter, Auggie)

Written 2026-11-18. Worktree `.claude/worktrees/usage-panel`, branch `usage-panel` (base `personal/main`).
No feature code has been written. Companion file: `docs/usage-panel-research.md` (sources, quotes, URLs).

## Contract (verbatim) and status

| # | User's words | Status |
|---|---|---|
| 1 | "I want a separate Usage button right into the config settings which shows the current account's usage that can be of claude usage, usage credits or even openrouter usage or auggie as well thats entirely in that" | NOT discharged — researched only |
| 2 | "research what kinds of usage are we talking about then go with the rest" | Research discharged (`docs/usage-panel-research.md`); "the rest" held by clause 3 |
| 3 | "hold on the plan -> review -> fix chain" | IN FORCE — no plan, review or code until the user lifts it |
| 4 | "we would make sure, ensure that we are registering accounts for Claude, OpenRouter and Auggie from the app, itself, today we have it for claude, can you give me a handover prompt/script where I could get them for the ones which we dont have today." | This file + the pointer prompt discharge the handover; the registration itself is NOT built |

## What exists today (from a repo map, not re-verified line by line — re-read before editing)

- Config dialog: `aitracker/web/ext_cr_dialogs.js` `renderConfig` (~:1731), tabs in the `sections` array (~:1742), `renderSection` if/else chain (~:1842). New tab = name in `sections` + branch in `renderSection` + an `xxxBlock()` that starts with `if (crReadOnly()) return null;`.
- Claude account registration (the only one): `claudeLoginBlock()` (~:1623) reads `GET /api/claude/auth`, shows "Log in" / "Switch account", and opens a dashboard terminal running `claude --session-id <uuid> /login`; `term_vt._login_watch()` removes the login-only transcript afterwards (rule-6 exception in `.claude/rules/conventions.md`).
- Server: `aitracker/server.py` `/api/claude/auth` (~:509), guard `_local_caller` (~:225), body whitelist `_CLAUDE_AUTH_KEYS` (~:245), tunnel allow-list `_RO_GET_ALLOW` (~:316).
- Auth status cache to copy: `aitracker/gateway.py` `claude_auth_status` (~:140) — 60 s TTL, single-flight, 5 s fresh floor.
- OpenRouter today: `gateway.py` `or_launcher()`, `openrouter_configured()`, `slots()`; config keys `OPENROUTER_LAUNCHER`, `OPENROUTER_SLOTS_FILE`. The tracker holds NO OpenRouter key and never reads `OPENROUTER_API_KEY` / `ANTHROPIC_AUTH_TOKEN`; the launcher script exports them.
- Auggie today: `providers/auggie.py` `agent_cli` descriptor (version + upgrade only). No login or auth-status call.
- Tests to copy: `tests/test_claude_auth_route.py`, `tests/test_claude_auth_status.py`, `tests/test_agents_ui.py`, `tests/test_claude_login_settings_ui.py`.

## What is missing

| Account | Registration from the app | Usage source once registered |
|---|---|---|
| Claude | Exists | `claude -p "/usage"` → `usage_report` (limits + usage credits). Emission from the bare CLI is inferred — probe first |
| Auggie | MISSING. Likely shape: an "Auggie: Log in / Switch account" row that opens a dashboard terminal running `auggie login`, with status from `auggie auth status`. Both commands must be confirmed on the installed 1.3.0-prerelease | No account balance source on 1.x (`auggie account status` was dropped). Only per-session cost from `~/.augment/sessions/*.json` |
| OpenRouter | MISSING. There is no vendor login CLI: "registering" means the app learning a key. Options: (a) read it from the launcher's own environment/file, never typed in the browser; (b) a key field in Config — conflicts with the "never store a password typed in the browser" rule (`config.py` ~:185-199) | `GET https://openrouter.ai/api/v1/key` with the normal key; account credits need a separate management key |

## Decisions (answered by the user 2026-11-18)

1. Claude usage: may the dashboard run `claude -p "/usage"` (new rule-6 exception; cached; loads the user's hooks/MCP; needs `--no-session-persistence`)?
   **Answer: "Yes, run it."**
2. OpenRouter: may the dashboard itself call `openrouter.ai` (first dashboard-owned socket — new rule-6 exception), and is the key read from the launcher (option a) or entered in Config (option b)?
   **Answer (verbatim): "2, enter key enter in the config and write it in the env file for this app, never display or show the existing key, can you share the env location, path where the key is stored"**, i.e. option (b) plus the dashboard calls openrouter.ai. Constraints: the key is typed in Config and persisted to this app's env file; the existing key is never displayed or echoed back. This overrides the `config.py` "never store a password typed in the browser" rule for this key only, so the plan must carry that as an explicit new exception. Env file location: see the next section.
3. Auggie: registration via a terminal running `auggie login` — yes? And for usage, show summed per-session cost labelled as such, or leave Auggie usage out?
   **Answer: terminal login yes; usage = summed per-session `cost_usd`, labelled "local session cost, not account balance".**

### Where the OpenRouter key would be stored (repo search, 2026-11-18)

- **No env file exists today.** `cli.py:49-58` reads only `os.environ`. The Makefile has no `include`/`.env`. The repo has no launcher script, and no code reads `OPENROUTER_API_KEY`. `OPENROUTER_LAUNCHER`/`OPENROUTER_SLOTS_FILE` default to empty (`config.py:637-638`), and the launcher's own key source is unknown from the repo.
- App state lives in the package dir: `flags.json` `config.py:11`, `titles.json` :14, `last_terms.json` :66, `config.json` :224. None of these can be overridden. `.gitignore` covers them but has no `.env` entry.
- The secret rule is at **`config.py:126-129`** (the "~:185-199" cite above is stale): "Writing a password typed into a web form into a plaintext JSON file on disk, on a server that may be reachable over a tunnel, is a real security regression, not a convenience". Today it covers `TRACKER_AUTH` (env-only, `config.py:131`; absent from `EDITABLE` `config.py:229`; rejected by `POST /api/config`, `server.py:768-772`).
- Live config writes: `POST /api/config` → `config.EDITABLE` (:229) + `config.VALIDATORS` (:304) → `_save_json(config.CONFIG_FILE, …)` at `server.py:798-799` (second write at :822-823, not inspected).
- `schedule.py:258-262` strips KEY/TOKEN/AUTH-named vars from the launchd plist, so the service can't receive the key through its environment.
- **Proposed (pending user confirmation):** a new `~/.ai-tracker.env`, chmod 600, outside every git tree and shared by all worktrees, holding only `OPENROUTER_API_KEY=`. The server reads it at call time. Config shows set/not-set + Replace and never the value. Needs a narrow exception to `config.py:126-129` and a statement on whether the user's launcher switches to read it.

### Follow-up answers (user, 2026-11-18)

- **Key file: `aitracker/config.json`** (the user chose this over `~/.ai-tracker.env`). The plan must carry a narrow exception to the secret rule at `config.py:126-129` for `OPENROUTER_API_KEY` only. The key is never returned by any GET, never shown in Config (set/not-set + Replace only), and never added to the launchd plist (`schedule.py:258-262`).
- **Launcher: "Yes, launcher reads it."** The user's `OPENROUTER_LAUNCHER` script (outside this repo) will read the key from `aitracker/config.json`. The plan documents the exact snippet (JSON, so e.g. `python3 -c` or `jq`); the user edits the launcher.
- **Probes: run by an agent** (read-only; shapes only, no emails, org names or key values).
- **Claude usage requirement (verbatim): "for claude, the usage must show the usage and also usage credits, whichever is true, since I have 2 accounts, 1 runs with usage credits and another is a Max plan which shows only usage"**, i.e. render plan-limit rows always, and the usage-credits block only when `extra_usage` is present/enabled. Both account kinds must render correctly. The probe sees only the currently logged-in account.
- **Hold lifted: "Go after probes."** Once the probe shapes are recorded below, an `opus` agent writes `docs/usage-panel-plan.md` → `opus` adversarial review → reconcile → user sign-off before code.

## Probe output shapes (recorded 2026-11-18)

Read-only probes run by an agent. Values are redacted: emails, org names and key values are never shown. Only the logged-in account was probed (`subscriptionType` = `max`, `planTier` = `max_5x`, i.e. the **Max plan**). The **usage-credits account was NOT probed**; its `extra_usage` shape is therefore unverified and must be confirmed when that account is logged in.

### 1. Claude `/usage` (stream-json)

Command:
```bash
claude -p "/usage" --output-format stream-json --verbose --no-session-persistence > usage.jsonl 2>usage.err   # timeout 180s
```

Line types (12 lines total, `usage.jsonl`):
```
(system, hook_started) x4      <- the user's hooks fired, as expected
(system, hook_response) x4
(system, init) x1
(system, commands_changed) x1
(assistant, None) x1           <- the /usage text plus usage_report (line 11, 0-based 10)
(result, success) x1
```

Where `usage_report` sits: **top-level key of the assistant line** (not inside `message`). Keys of that line: `type, message, parent_tool_use_id, local_command_source, session_id, uuid, timestamp, usage_report, local_command_run`.

Verdict: bare CLI DOES emit `usage_report`, at top-level of the `assistant` line (`usage_report` count = 1).

usage_report structure (values redacted, real types):
```
usage_report: object
  session: object
    total_cost_usd: int = 0
    total_api_duration_ms: int = 0
    total_duration_ms: int = 68438
    total_lines_added: int = 0
    total_lines_removed: int = 0
    model_usage: object
  rate_limits: object                      (keys: extra_usage, limits)
    limits: array[3]
      [0]: kind='session'        group=<str>  percent=87  resets_at=<ISO-8601 str>  scope=null                                  severity='warning'  is_active=True
      [1]: kind='weekly_all'     group=<str>  percent=84  resets_at=<ISO-8601 str>  scope=null                                  severity='warning'  is_active=False
      [2]: kind='weekly_scoped'  group=<str>  percent=4   resets_at=<ISO-8601 str>  scope={model:{display_name:'Fable'}, surface:null} severity='normal'  is_active=False
    extra_usage: object
      is_enabled: bool = False
      monthly_limit: int = 10000
      used_credits: int = 0
      utilization: int = 0
      currency: str = 'USD'
```

`extra_usage` on this Max account: PRESENT and `is_enabled=False`. The usage-credits block must render only when `is_enabled` is true; that branch is not exercised by this probe.

Plain-text `/usage` report (first lines, verbatim, nothing to redact):
```
You are currently using your subscription to power your Claude Code usage

Current session: 87% used · resets Nov 18 at 3:49pm (Asia/Calcutta)
Current week (all models): 84% used · resets Nov 23 at 3:29am (Asia/Calcutta)
Current week (Fable): 4% used · resets Nov 23 at 3:29am (Asia/Calcutta)

What's contributing to your usage?
Approximate · sessions on this machine only · shares overlap

Last 24h · 8449 requests · 30 sessions
  69%  Review sessions active over many hours · whole sessions with requests in 8 or more separate hours
  62%  Start fresh when you switch tasks · run /clear
  61%  Run fewer sessions at once · up to 14 at once
  47%  Check which model "general-purpose" subagents use
  Top skills: /head-out 1%, /branch-sync 1%
  Top subagents: general-purpose 47%, reviewer 16%, Plan 6%, head-out 1%, researcher 1%

Last 7d · 36969 requests · 89 sessions
  ...(same four rows, plus "Top MCP servers: claude.ai Slack 1%")
```

Billing: no model tokens billed. Result line: all `usage` token counts 0, `total_cost_usd` = 0, `num_turns` = 0, `modelUsage` empty.

`claude auth status --json` key names: `analyticsDisabled, apiProvider, authMethod, configDirectory, consoleProfileSignInOffered, email, loggedIn, loginExpiresAt, orgId, orgName, planTier, projectsDirectory, storedClaudeAiLogin, subscriptionType`. Values probed: `authMethod`=`claude.ai`, `subscriptionType`=`max`, `planTier`=`max_5x`. (`email`, `orgId`, `orgName`, `configDirectory` not printed.)

### 2. Auggie login and auth

Commands:
```bash
auggie --help 2>&1 | grep -iE "login|logout|auth|account"
auggie auth status 2>&1 | head -30
auggie login --help 2>&1 | head -30
```

Output shape:
```
  auggie auth login [--headless] [--json]  Authenticate the platform session in session.json
  auggie auth logout               Remove the local platform session without server revocation
  auggie auth status               Show the current platform authentication status
  auggie token revoke              Revoke tokens for the current authenticated user in the current tenant, then remove the CLI-owned local session
                                 Authenticate with inline session JSON or a session-file path; valid input takes precedence over other sources
Logged in.
Use `auggie auth login`; top-level authentication commands are no longer supported.
```

Verdict: the login/auth commands are `auggie auth login|logout|status` and `auggie token revoke`. The top-level `auggie login` is removed; `auggie login --help` only points to `auggie auth login`. `auggie auth status` prints a single line (`Logged in.`) with no account fields, so it cannot identify the account. Account identity would need another source, not verified.

### 3. OpenRouter

Not run: `OPENROUTER_API_KEY` is unset in the agent shell (presence check printed `unset`). No search for the key was made. Shape from docs (research §3).

## First step for the next session — probe, do not assume (run by the user or with their go-ahead)

```bash
# 1. Does the bare CLI emit the structured usage report? Expect a count >= 1.
claude -p "/usage" --output-format stream-json --verbose --no-session-persistence | grep -c usage_report

# 2. What does Auggie offer for registration on the installed version?
auggie --help | grep -iE "login|logout|auth|account"
auggie auth status

# 3. Does the OpenRouter key the launcher uses answer? (prints usage fields, never the key)
curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print({k:d.get(k) for k in ("label","usage","usage_monthly","limit","limit_remaining","is_free_tier")})'
```

Record the real output shapes in this file (conventions rule 7) before any parser is written.

## Then

Once clause 3 is lifted and the three decisions are answered: plan (separate `opus` agent, written to `docs/usage-panel-plan.md`) → adversarial review (`opus`) → reconcile → user sign-off → implement through `/tracker-gap` → review → `/branch-sync`, gate, push `usage-panel` to `personal`.

## Plan → review → reconcile (2026-11-18)

Files, side by side: plan `docs/usage-panel-plan.md` (opus) · reviews `docs/usage-panel-review-security.md` (opus: 1 blocker/3 major/11 minor) and `docs/usage-panel-review-ui.md` (opus: 0/4/9) · this verdict table (main thread) · clean plan = the plan file revised in place by its opus author with the accepted rows below.

| # | Finding | Verdict | Disposition |
|---|---|---|---|
| S-B1 | `GET /api/file` (`server.py:571-584`) serves any path with no `_tunnel_route_ok`/Host check, so a DNS-rebinding page can read `config.json` (live-repro'd on 8790/8787 with a harmless file) | **Confirmed**, and **pre-existing**: `TUNNEL_PASS` in config.json is readable this way today | Accept the one-line `_tunnel_route_ok()` guard; it lands in step 2, before the key can be stored |
| S-M1 | Shared cache: a failed run with no prior good value re-runs on every poll; `?fresh=1` bypasses the floor, backoff and no-retry-after-401 rules | Confirmed (plan logic gap) | Accept: cache failures with a timestamp; `fresh` honours the floor and backoff |
| S-M2 = U-M2 | `bundle.py` rewrites only `config.`/`tunnel.` prefixes, so `accounts.X` is a NameError; header lacks `urllib.request`/`urllib.error` | Confirmed by both independently | Accept the import-names + header fix. **Overengineered test trimmed**: one static test, not three |
| S-M3 | A cross-site `<img>` passes `_local_caller`, so it can trigger the 70 s `claude -p` run and the OpenRouter fetch | Confirmed | Accept a `Sec-Fetch-Site` check on the 4 new routes, independent of D2 (OpenRouter is triggerable too) |
| U-M1 | Auggie cost reads legacy `~/.augment/sessions` | **Partly confirmed**: `sessions/` newest Sep 16, i.e. no Auggie use since then. `sessions-v2/` holds only an empty directory created by the 15:07 probe (main thread first misread it as a file; corrected by the plan author, R1). No v2 shape exists to parse yet | Plan must read `sessions-v2` (shape confirmed from a real file first, conventions rule 7). It probably also means the provider no longer lists current Auggie sessions: user decision U1 |
| U-M3 = S-minor | Opening Config → Server calls openrouter.ai just to show set/not-set | Confirmed | Accept `?peek=1` (config read only, never a fetch) |
| U-M4 | Usage-credits branch rests on an unprobed shape | **Overstated**: fields and cents are documented (SDK `SDKUsageReport`). The real unknown is whether a usage-based-billing account returns `usage_report` at all | Accept gating only fixtures B/C and the credits branch on probe 0(c); the rest proceeds |
| S-minors | `_save_json` `mode=` + `fchmod` (not umask-masked); `claude_auth_cached()` (the API the plan named doesn't exist); drop the session-file-hiding fallback (`update._run` exposes no pid); rule-6 wording (D2 brackets, the "no other outbound" contradiction, proxy); `autocomplete="new-password"`; close `HTTPError`, TLS message, per-socket timeout; probe 0(b) must prove MCP servers are skipped; 0(c) is a stop-and-ask gate | Confirmed | Accept all |
| S-minor | Shared-cache `sync` mode is a second path | Confirmed overengineering | Accept: drop it |
| S-minor | Lost-update race between `tunnel.py`'s writer and the key write | Confirmed, pre-existing | No change; document as a known gap in the PR |
| S-m11 | Primary checkout `aitracker/config.json` is 644 and holds `TUNNEL_PASS` | Confirmed, live | User action: `chmod 600` (not done by the session; it's the live checkout) |
| — | **Missed by both:** `aitracker/config.json` is per-checkout. The key saved via the 8790 service lands in the primary checkout's file. The launcher snippet must use that absolute path, and a worktree-run server sees no key | Main thread | Plan must state it in the launcher snippet and the key row's help text |
| — | **Not examined by either:** behaviour when the dashboard runs as the launchd service with a different PATH (finding `claude`/`auggie` via `shutil.which`) | Main thread | Plan to state it reuses `agent_cli`'s resolution |

## Sign-off (user, 2026-11-18)

- **D1:** OpenRouter key row in **Config → Server**.
- **D2:** **Yes**: run `/usage` with `--settings '{"disableAllHooks":true}' --strict-mcp-config`, only if probe 0(b) shows `usage_report` still comes back; otherwise the plain approved run.
- **D3:** Auggie cost window = calendar month to date, UTC (approved with the plan).
- **U1:** "write a separate handover script/prompt for that" → `docs/auggie-sessions-v2-handover.md`. Not part of this plan.
- **Plan rev 2 APPROVED: "Approve, implement."** Implementation through `/tracker-gap` (sonnet implements, haiku gates), then an opus implementation review. Gates 0(c) (usage-credits account probe) and 0(f) (one real `auggie -p` session) stop and ask the user when reached.

## Implementation-time probes (2026-11-18, implementer)

Shapes and verdicts only; no emails, org names or secrets.

- **0(a) `/usage` footprint** (`touch` marker, one `claude -p /usage --output-format stream-json --verbose --no-session-persistence` in `~`): `~/.claude/history.jsonl` line count unchanged (6364 before and after); no new file under `~/.claude/sessions` or under `~/.claude/projects/-Users-<home>`. A transient `~/.claude/sessions/<pid>.json` while the process runs cannot be observed after the fact; the plan already records it as a known cosmetic gap. The run took 25 s with the user's hooks and MCP servers.
- **0(b) with D2 flags** (`--settings '{"disableAllHooks":true}' --strict-mcp-config`): `usage_report` still returned (top-level key of the one `assistant` line, a dict); `system/init` `mcp_servers` = `[]`; `hook_*` lines = 0 (3 lines in total: init, assistant, result); `num_turns` 0, cost 0, `is_error` false; 18 s. **Verdict: D2 applies**; the run uses the flags and the rule-6 text carries the D2 wording.
- **The account these probes saw was NOT the Max plan.** `usage_report.rate_limits` = `{limits: [] (empty list), extra_usage: {is_enabled: true, monthly_limit: int (minor units), used_credits: int, utilization: float, currency: "USD"}}`. So the logged-in account at probe time is the usage-credits account: `usage_report` IS returned, with an empty `limits` list and an enabled `extra_usage`. **`extra_usage` sits inside `rate_limits`, not at the top level of `usage_report`**, and the amount fields are `monthly_limit` / `used_credits`. This unblocks the credits branch (probe 0(c), step 3b) technically; it stays **pending the user's go** as instructed.
- **0(d) `auggie auth status`** from `~`: `Logged in.` rc 0; no file under `~/.augment` newer than the marker.
- 0(c), 0(e), 0(f): not run (user-gated).

## Implementation status (2026-11-18)

Done: steps 1, 2, 3a, 4, 5, 6 and 7 (doc lines) of `docs/usage-panel-plan.md`. Pending, user-gated: step 3b (credits branch + fixtures B/C; `accounts._acct_parse_usage_report` returns `credits = None`, and the UI already renders a non-null `credits` block) and step 3c (Auggie sessions-v2 reader, probe 0(f)). With 3b pending, the credits account renders as "No plan limits reported for this login." with no credits block.
