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

## Decisions the user still owes (ask before planning)

1. Claude usage: may the dashboard run `claude -p "/usage"` (new rule-6 exception; cached; loads the user's hooks/MCP; needs `--no-session-persistence`)?
2. OpenRouter: may the dashboard itself call `openrouter.ai` (first dashboard-owned socket — new rule-6 exception), and is the key read from the launcher (option a) or entered in Config (option b)?
3. Auggie: registration via a terminal running `auggie login` — yes? And for usage, show summed per-session cost labelled as such, or leave Auggie usage out?

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
