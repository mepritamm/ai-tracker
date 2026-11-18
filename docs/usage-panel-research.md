# Usage panel research: what usage exists and where to read it (as of 2026-11-17)

Locally installed: Claude Code **2.1.326** (`~/.local/share/claude/versions/`) and Auggie **1.3.0-prerelease.202611160911** (`/opt/homebrew/lib/node_modules/@augmentcode/auggie/package.json`).

---

## 1. Claude Code on a claude.ai subscription (Pro / Max / Ultra / Team / Enterprise)

### What usage kinds exist
- **Five-hour session limit.** It starts with your first message and resets five hours later. Verified Ultra accounts have none. Source: support.claude.com "How do usage and length limits work?" (https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work): "The five-hour limit controls how much you can use Claude within a five-hour period." / "The period starts when you send your first message."
- **Weekly limit across all models.** It resets at a fixed time assigned to the account. Same article: "Weekly limits apply across all models." Max page (https://support.claude.com/en/articles/11049741-what-is-the-max-plan): "The weekly limit resets at a fixed time each week that is assigned to your account."
- **Scoped weekly limits.** The documented one is "a separate weekly limit for Fable" (Max page). Claude Code's error list also has model-family limits: "You've hit your Opus limit" and "You've hit your Sonnet limit" (https://code.claude.com/docs/en/costs, section "When a developer asks about a limit"). The Agent SDK types model these as `kind: weekly_scoped` rows with a `scope.model` or `scope.surface`.
- **Team/Enterprise.** "each member's Claude Code usage draws from a per-seat allowance that resets on a rolling five-hour window and a weekly window. The allowance is shared with Claude chat and Cowork" (https://code.claude.com/docs/en/costs).
- **Limit resets.** Some accounts get one-shot "Reset for free" grants under Settings > Usage. You cannot trigger them from the terminal (support search results, article 17007452).
- **Usage credits.** See §2.

### In-CLI screens (documented)
- `/usage` (aliases `/cost`, `/stats`): "Show session cost, plan usage limits, and activity stats. On a Pro, Max, Ultra, Team, or Enterprise plan, includes a breakdown of what counts against your plan limits" (https://code.claude.com/docs/en/commands). When the request fails it falls back to the last-known bars from the past 60 minutes, and "most often because the usage endpoint is rate limited" (https://code.claude.com/docs/en/costs).
- `/status`: "showing version, model, account, and connectivity" (commands page). It shows Login, Organization and Email rows. It does not show usage.

### Non-interactive sources

**(a) Agent SDK `usage_report` from a `/usage` prompt.** This is the best documented structured source.
- Docs: https://code.claude.com/docs/en/agent-sdk/typescript (section `SDKUsageReport`). Quotes:
  - "When you send `/usage` as a prompt, Claude Code delivers the report as an assistant message whose `message.content` holds the text. It attaches `usage_report` to that same message only when … The session authenticates with a claude.ai credential / The credential shows a known plan type or carries the `user:profile` scope / The account isn't on usage-based billing."
  - "A `claude setup-token` token passed as `CLAUDE_CODE_OAUTH_TOKEN` doesn't qualify by default."
  - "The type is experimental: its shape may change."
- Fields:
  - `rate_limits.limits[]` = {`kind` (e.g. `session`, `weekly_all`, `weekly_scoped`), `group`, `percent` 0-100, `resets_at` ISO 8601 or null, `scope.model.display_name` / `scope.surface.display_name`, `severity` (`normal`/`warning`/`critical`), `is_active`}
  - `rate_limits.extra_usage` = {`is_enabled`, `monthly_limit`, `used_credits`, `utilization`, `currency`}, amounts "in minor units of `currency`, cents for USD"
  - `session.{total_cost_usd, model_usage, …}` (local estimate)
  - Docs: "`limits` holds the server's usage rows as the server sent them … render the rows verbatim." and "`monthly_limit` is `null` when this account has no spending cap of its own. On Team and Enterprise plans, don't render `null` as unlimited."
- Inferred, not documented for the bare CLI: `claude -p "/usage" --output-format stream-json --verbose` should emit the same message, because the SDK is a wrapper over the CLI's stream-json. The installed 2.1.326 binary does contain `usage_report`, described as "Structured twin of the /usage report, carried on the synthetic assistant message…".
- Network: the CLI calls the usage endpoint (see (d)). The dashboard itself opens no socket, the same pattern as the existing `claude auth status` exception.
- Caveats:
  - `--bare` cannot be used. "In bare mode, Claude Code never reads OAuth credentials" (https://code.claude.com/docs/en/headless). A non-bare `-p` therefore loads the user's hooks and MCP servers.
  - Use `--no-session-persistence`, or the run writes a transcript that the tracker would then list.
  - Whether a `/usage` prompt spends any model tokens is not documented (likely none, because it is a local command).
  - The endpoint is rate limited, so cache results and poll rarely.

**(b) Statusline JSON input.** Documented, but only reachable via the user's statusline script.
- Docs: https://code.claude.com/docs/en/statusline.
- Fields:
  - `rate_limits.five_hour.used_percentage` and `rate_limits.seven_day.used_percentage`: "Percentage of the 5-hour or 7-day rate limit consumed, from 0 to 100"
  - `rate_limits.*.resets_at`: "Unix epoch seconds when the 5-hour or 7-day rate limit window resets"
  - `rate_limits.spend_limit.{used_percentage, resets_at, used_usd, limit_usd, period}`: only behind a Claude apps gateway
- Availability: "`rate_limits`: appears only for claude.ai Pro, Max, and Ultra subscribers, or behind a Claude apps gateway that sets a spend limit for you. Even then, it appears only after the first API response in the session." This means no Team/Enterprise and no per-model rows.
- The dashboard cannot read a statusline's stdin. It would need the user's statusline command to tee the JSON to a file, and installing that means editing `~/.claude/settings.json`, which is a write.

**(c) Local files** (documented in https://code.claude.com/docs/en/claude-directory unless marked otherwise):
- `~/.claude/stats-cache.json`: "Aggregated token and cost counts shown by `/usage`". Observed top-level keys: `version, lastComputedDate, dailyActivity, dailyModelTokens, dailyModelTokensVersion, modelUsage, totalSessions, totalMessages, longestSession, firstSessionDate, hourCounts`. It holds activity and token history only, with **no plan-limit percentages**. No network.
- `~/.claude.json`: "Holds account details…". Observed but **undocumented** keys: per-project `lastCost`, `lastModelUsage`, `lastTotalInputTokens`, and a top-level `cachedExtraUsageDisabledReason` (value begins `out_of_cred…`). It holds no limit percentages. I did not find where the "last-known usage" snapshot is stored.
- `~/.claude/usage-data/` holds `/insights` reports. These are not limits.

**(d) HTTP endpoint the CLI calls.** Unofficial and undocumented.
- Endpoint: `GET https://api.anthropic.com/api/oauth/usage`. The installed binary also has variants `?skip_spend=1`, `?at_wall=1`, `?cedar_ember=1`.
- Headers: `Authorization: Bearer <claude.ai OAuth access token>` and `anthropic-beta: oauth-2025-04-20`. The constant is present in the binary.
- Response, per third-party crates (cship 1.7.1 https://docs.rs/crate/cship/1.7.1/source/src/usage_limits.rs and clauth 0.5.5 https://docs.rs/crate/clauth/0.5.5/source/src/usage/fetch.rs):
  - `five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`, `seven_day_cowork`, `seven_day_oauth_apps`, each {`utilization` 0-100, `resets_at`}
  - `extra_usage` {`is_enabled`, `monthly_limit`, `used_credits`, `utilization`, `currency`}
- Sibling endpoint `GET /api/oauth/profile` returns `account.has_claude_max`, `account.has_claude_pro`, `organization.organization_type` and `organization.rate_limit_tier`.
- Credential: the OAuth token is in the macOS Keychain, or in `~/.claude/.credentials.json` when the Keychain is unavailable (https://code.claude.com/docs/en/authentication: "On macOS, credentials are stored in the encrypted macOS Keychain…").
- **The dashboard would have to open a socket and read the user's OAuth secret.** Not recommended.

**(e) `claude auth status --json`.**
- Docs (https://code.claude.com/docs/en/cli-reference): "Show authentication status as JSON… The JSON's `authMethod` field is one of `none`, `claude.ai`, `oauth_token`, `api_key`, `api_key_helper`, or `third_party`." The rest of the schema is undocumented.
- Keys observed locally (repo `reports/claude-login-button-review.md:88`): `analyticsDisabled, apiProvider, authMethod, configDirectory, consoleProfileSignInOffered, email, loggedIn, loginExpiresAt, orgId, orgName, planTier, projectsDirectory, storedClaudeAiLogin, subscriptionType`.
- `subscriptionType` (e.g. `max`, `enterprise`) and `planTier` identify the plan. It carries no usage numbers.
- Agent SDK `AccountInfo` = {`email?`, `organization?`, `subscriptionType?`, `tokenSource?`, `apiKeySource?`} (TypeScript SDK docs).

**No `claude usage` subcommand exists.** The CLI reference lists none.

---

## 2. Usage credits (formerly "extra usage") and Console/API accounts

### Usage credits on subscriptions
- **Current official name: "usage credits."** Commands page: "`/usage-credits` | Configure usage credits, or request them from your admin… Previously `/extra-usage`". The support article (https://support.claude.com/en/articles/12429409-extra-usage-for-paid-claude-plans) uses "usage credits" throughout. The API field is still named `extra_usage`.
- **Numbers that exist:**
  - Monthly spend limit
  - "Current spending" (month to date)
  - Balance of purchased credits
  - Auto-reload (web only)
  - On or off
  - https://code.claude.com/docs/en/costs: "In its **Usage credits** section you can turn usage credits on or off and check your credit balance, this month's spend, and your monthly spend limit". Plans: Pro, Max, Ultra. Team and Enterprise use org, group or member limits.
- **Readable via:**
  - `usage_report.rate_limits.extra_usage` (§1a): `is_enabled`, `monthly_limit`, `used_credits`, `utilization`, `currency`. **It has no balance field**, so the balance is only on claude.ai Settings > Usage.
  - Unofficial `/api/oauth/usage` `extra_usage` (§1d)
  - `/usage` usage-credits row: "your spend for the current month, measured against your monthly spend limit… When you haven't set a limit, the row shows `Unlimited`" (costs page)

### Claude Console / API-key accounts
- **Usage and Cost Admin API**, now legacy but supported (https://platform.claude.com/docs/en/manage-claude/usage-cost-api):
  - Endpoints: `GET https://api.anthropic.com/v1/organizations/usage_report/messages` (buckets `1m`/`1h`/`1d`; uncached input, cache read, cache creation and output tokens; group by model, workspace, API key, etc.) and `GET /v1/organizations/cost_report` ("All costs are in USD, reported as decimal strings in lowest units (cents)", `1d` only). Both paginate with `has_more`/`next_page`.
  - Headers: `x-api-key: $ANTHROPIC_ADMIN_KEY` and `anthropic-version`.
  - Credential: "You can access them using an Admin API key, an OAuth token with the `org:admin` scope, or a personal or service account key that isn't scoped to a workspace; workspace API keys don't work." Key format is `sk-ant-admin01-...`. "Only organization members with the admin role can provision one" (admin-api page).
  - Availability: "The Admin API isn't available to organizations on the claude.ai Team plan or to individual Claude Console accounts."
  - Freshness: "typically appears within 5 minutes". Polling "once per minute for sustained use".
  - For new integrations: the Usage and Cost Analytics API.
- **Credit balance with a normal API key: no documented endpoint.**
  - GitHub issue anthropics/claude-code#47574 (https://github.com/anthropics/claude-code/issues/47574) reports "`GET /v1/organizations/balance` returns 404". It was closed as not planned by the inactivity bot, with no maintainer reply.
  - The balance is shown only on the Console Billing page. The only in-band signal is the `credit_balance_too_low` error.
- All of the above are network calls from the dashboard to `api.anthropic.com` with an admin credential.

---

## 3. OpenRouter

- **`GET https://openrouter.ai/api/v1/key`** returns info on the key "associated with the current authentication session". It takes a normal key as `Authorization: Bearer`. Limits page (https://openrouter.ai/docs/api-reference/limits): "To check the rate limit or credits left on an API key, make a GET request to `https://openrouter.ai/api/v1/key`."
  - Fields in `data` (https://openrouter.ai/docs/api-reference/api-keys/get-current-key):
    - `label`
    - `limit` ("Credit limit for the key, or null if unlimited")
    - `limit_remaining` ("Remaining credits for the key, or null if unlimited")
    - `limit_reset`
    - `include_byok_in_limit`
    - `usage` ("Number of credits used (all time)"), `usage_daily`, `usage_weekly`, `usage_monthly` (UTC day, Monday-start week, month)
    - `byok_usage*`
    - `is_free_tier` ("Whether the user has paid for credits before")
    - `free_model_daily_requests` {`used`, `limit`, `remaining`}
    - `budgets`, `effective_budget`
    - `is_management_key`, `expires_at`, `organization_id`, `workspace_id`, `creator_user_id`, `allowed_data_regions`
    - `rate_limit` is "deprecated… safe to ignore"
  - Free-model limits: 20 requests per minute, and 50 per day (under 10 credits purchased) or 1000 per day.
- **`GET /api/v1/credits`** returns `data.total_credits` ("Total credits purchased") and `data.total_usage` ("Total credits used"). It needs a **management key**: "Only management keys can perform this operation" (https://openrouter.ai/docs/api-reference/get-credits). Account balance = total_credits − total_usage.
- **`GET /api/v1/activity`** returns the last 30 completed UTC days. It needs a **management key**. Params: `date`, `api_key_hash`, `user_id`, `group_by=workspace`, `workspace_id`. Item fields: `date, model, model_permaslug, endpoint_id, provider_name, usage, byok_usage_inference, requests, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens`. Source: https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity-grouped-by-endpoint.
- **Management keys** "cannot be used to make API calls to OpenRouter's completion endpoints" (https://openrouter.ai/docs/guides/overview/auth/management-api-keys). The key Claude Code uses is therefore a normal key, which can read only `/key`.
- **Claude Code on OpenRouter** (https://openrouter.ai/docs/guides/guides/claude-code-integration):
  - Settings: `ANTHROPIC_BASE_URL="https://openrouter.ai/api"`, `ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY"`, and `ANTHROPIC_API_KEY=""` ("Must be explicitly empty").
  - Where they go: the shell profile (recommended), or the `env` block of `.claude/settings.local.json`, "Do not put these in a project-level `.env` file."
  - `/status` should show "Auth token: ANTHROPIC_AUTH_TOKEN".
  - In Claude Code auth precedence, `ANTHROPIC_AUTH_TOKEN` is #2, "Sent as the `Authorization: Bearer` header" (authentication docs).
- There is **no vendor CLI** to delegate to, so any number here requires **the dashboard itself to call openrouter.ai** with a key it read from env or settings. That needs a new conventions rule-6 exception.

---

## 4. Auggie (Augment Code CLI)

- **Usage units today:** dollars under token-based pricing. "All three components draw from the same usage balance". Business plan "$100 across LLM tokens, compute, and service fees". "The $100 of included usage resets at the start of each billing cycle." After that it is pay-as-you-go (https://docs.augmentcode.com/models/token-based-pricing). Legacy "credits" remain "on legacy credit-based Enterprise contracts" (https://docs.augmentcode.com/analytics/credit-dashboard-and-quotas). Enterprise budgets "reset at the beginning of each calendar month (UTC)". "User messages" were not found in current docs (UNRESOLVED).
- **Account and plan from the CLI:**
  - **Auggie 0.x** (https://docs.augmentcode.com/cli/v0/reference): "`auggie account status` | Show account and billing information".
    - 0.24.0 changelog: "`auggie account status` now supports a `--json` flag for machine-readable output."
    - 0.25.0: "Account display now shows a billing summary with credits and cost breakdown…"
    - 0.34.0: "Included billing information in CLI JSON output."
    - JSON field names are not documented. Third parties say it gives plan, remaining and included credits, and cycle end.
  - **Auggie 1.x** (current docs say "Auggie 1.x.x (prerelease)", https://docs.augmentcode.com/cli/reference) has no `account` command anywhere. The installed 1.3.0-prerelease help text likewise lists none. `/about` = "Show version, environment, and session info". `auggie auth status` = "Show the current platform authentication status", with no documented plan field.
  - **So on the installed version, no CLI command returns the account balance or plan.**
- **Session-level (1.x):**
  - `auggie session stats [sessionId] --json`: "Display session statistics including cost/credit usage" (installed help).
  - `--show-cost` (alias `--show-credits`): "Include cost/credit usage in print-mode output".
  - Probably computed locally (inferred).
- **Local files:**
  - `~/.augment/sessions/*.json` carry a per-exchange `billing_metadata` {`transaction_id`, `credits_consumed`, `cost_usd`, `usage_unit`, `effective_model_name`} (observed). ai-tracker already sums `cost_usd` at `aitracker/providers/auggie.py:607-610`.
  - `~/.augment/session.json` is the login session (credentials). I did not inspect it, and no plan or usage file was found.
  - Nothing stores the account balance.
- **APIs:**
  - Official: the web dashboard at app.augmentcode.com ("Remaining included usage and pay-as-you-go spend"), and an enterprise Analytics API (service account plus token).
  - Unofficial (CodexBar, https://raw.githubusercontent.com/steipete/CodexBar/main/docs/augment.md): `app.augmentcode.com/api/credits` and `/api/subscription` with browser session cookies. Not usable without a socket and cookies.

---

## Summary table

| Usage kind | Account type | Best source | Dashboard needs network itself? | Documented? | Confidence |
|---|---|---|---|---|---|
| 5h session %, reset | Pro/Max/Ultra/Team/Ent | `claude -p "/usage" --output-format stream-json --no-session-persistence` → `usage_report.rate_limits.limits[kind=session]` | No (the CLI calls api.anthropic.com) | SDK type documented (experimental); bare-CLI emission inferred | LIKELY |
| Weekly all-models %, reset | same | same, `kind=weekly_all`; or statusline `rate_limits.seven_day` (Pro/Max/Ultra only) | No | Yes (SDK and statusline docs) | LIKELY / CONFIRMED (statusline) |
| Scoped weekly (Fable/Opus/Sonnet/surface) | Max/Ultra etc. | `usage_report` `kind=weekly_scoped` + `scope` | No | Yes (SDK) | LIKELY |
| Plan identity | any Claude login | `claude auth status --json` → `subscriptionType`, `planTier` | No (the CLI may contact Anthropic) | `authMethod` documented; other keys observed only | CONFIRMED (observed) |
| Usage-credits on/off, monthly limit, spent | Pro/Max/Ultra (+Team/Ent own limit) | `usage_report.rate_limits.extra_usage` (minor units) | No | Yes (SDK) | LIKELY |
| Usage-credits balance | Pro/Max/Ultra | claude.ai Settings > Usage only | n/a | Yes (web only) | CONFIRMED (no programmatic source) |
| Local activity/token history | any | `~/.claude/stats-cache.json` | No | Yes (file listed; schema not) | CONFIRMED |
| Raw limits incl. opus/sonnet + extra_usage | claude.ai OAuth | `GET api.anthropic.com/api/oauth/usage` + Keychain token | **Yes**, and reads the OAuth secret | No (unofficial) | LIKELY (in binary 2.1.326) |
| Org usage/cost reports | Console org (not individual, not Team) | Admin API `usage_report/messages`, `cost_report` | **Yes** + admin key | Yes | CONFIRMED |
| API credit balance | Console | none (Billing page only) | n/a | No endpoint | CONFIRMED absent (per issue #47574; no official denial) |
| Key usage/limit/remaining, daily/weekly/monthly | OpenRouter | `GET openrouter.ai/api/v1/key` (normal key) | **Yes** | Yes | CONFIRMED |
| Account credits total/used | OpenRouter | `GET /api/v1/credits` (management key) | **Yes** | Yes | CONFIRMED |
| Per-day model activity | OpenRouter | `GET /api/v1/activity` (management key) | **Yes** | Yes | CONFIRMED |
| Account balance/plan/renewal | Auggie 0.x | `auggie account status --json` | No (CLI; network by CLI presumably) | Yes (0.x docs + changelog); fields not | LIKELY |
| Account balance/plan/renewal | Auggie 1.x (installed) | none in CLI; app.augmentcode.com web only | n/a (unofficial cookie API would need a socket) | Command absent from 1.x docs and help | CONFIRMED absent |
| Per-session cost/credits | Auggie | local `~/.augment/sessions/*.json` `billing_metadata` (already parsed); `auggie session stats --json` | No | Field observed; stats command in help | CONFIRMED |

## Key caveats
1. The only documented, no-socket way to get plan limits is to run the vendor's CLI with `/usage`. Running the `claude` binary needs a new conventions rule-6 exception, like the existing `claude auth status` one. Limits on that route:
   - `--bare` can't be used, so user hooks and MCP servers load.
   - It needs `--no-session-persistence`.
   - The usage endpoint is rate limited, so cache it the way auth status is cached.
2. Statusline `rate_limits` is Pro/Max/Ultra only, appears after the first API response, and cannot be read by the dashboard without editing the user's statusline config.
3. `/api/oauth/usage` is unofficial. Using it means the dashboard opens a socket and handles the user's OAuth token. Avoid.
4. Anyone with an API key, Console org or OpenRouter setup gets no plan bars. OpenRouter numbers require the dashboard to call openrouter.ai itself.
5. Installed Auggie 1.3.0-prerelease has dropped `auggie account`, so its account balance has no CLI or local source.

Sources: https://code.claude.com/docs/en/statusline · https://code.claude.com/docs/en/costs · https://code.claude.com/docs/en/commands · https://code.claude.com/docs/en/cli-reference · https://code.claude.com/docs/en/claude-directory · https://code.claude.com/docs/en/authentication · https://code.claude.com/docs/en/headless · https://code.claude.com/docs/en/agent-sdk/typescript · https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work · https://support.claude.com/en/articles/11049741-what-is-the-max-plan · https://support.claude.com/en/articles/12429409-extra-usage-for-paid-claude-plans · https://platform.claude.com/docs/en/manage-claude/usage-cost-api · https://platform.claude.com/docs/en/manage-claude/admin-api · https://github.com/anthropics/claude-code/issues/47574 · https://docs.rs/crate/cship/1.7.1/source/src/usage_limits.rs · https://docs.rs/crate/clauth/0.5.5/source/src/usage/fetch.rs · https://openrouter.ai/docs/api-reference/limits · https://openrouter.ai/docs/api-reference/api-keys/get-current-key · https://openrouter.ai/docs/api-reference/get-credits · https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity-grouped-by-endpoint · https://openrouter.ai/docs/guides/overview/auth/management-api-keys · https://openrouter.ai/docs/guides/guides/claude-code-integration · https://docs.augmentcode.com/cli/reference · https://docs.augmentcode.com/cli/v0/reference · https://docs.augmentcode.com/models/token-based-pricing · https://docs.augmentcode.com/analytics/credit-dashboard-and-quotas · https://www.augmentcode.com/changelog/auggie-cli-0-24-0-release-notes · https://www.augmentcode.com/changelog/cli-0-25-0-release-notes · https://www.augmentcode.com/changelog/auggie-cli-0-34-0-release-notes · https://raw.githubusercontent.com/steipete/CodexBar/main/docs/augment.md

Local evidence paths:
- `/Users/pritammondal/.local/share/claude/versions/2.1.326`: binary contains `/api/oauth/usage`, `oauth-2025-04-20`, `usage_report`, `BASE_API_URL:"https://api.anthropic.com"`
- `/opt/homebrew/lib/node_modules/@augmentcode/auggie/auggie-v2.mjs`: help text at ~line 6201-6223 (no `account` command); `session stats --json` at ~line 12170
- `/Users/pritammondal/.augment/sessions/1d6ef2cb-b1b4-4bea-83fa-b55c4a204cf5.json:111-117`: `billing_metadata` shape
- `/Users/pritammondal/.claude/stats-cache.json`: key names
- `/Users/pritammondal/.claude.json`: key names only
- `/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/.claude/worktrees/usage-panel/reports/claude-login-button-review.md:88`: observed `claude auth status` keys
- `/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/.claude/worktrees/usage-panel/aitracker/providers/auggie.py:607-610`: existing Auggie cost parsing
