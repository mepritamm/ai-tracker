# Adversarial review: Claude Code login button plan v1 (reviewer: opus)

Reviewed: `reports/claude-login-button.md` (plan v1), against `personal/main` @ adeb6fa in this worktree.
Brief: assume the plan is wrong. Read-only. No real login was run. Read-only CLI used:
`claude --version` (2.1.325) and `claude auth status --json`, with only its KEYS and timing printed.

**Verdict:** the plan's L2 path is sound. It reuses the proven `/model` inject path. The L1 hinge
is handled badly in two ways. Its only proof is scheduled last, after all the code is built. Its
fallback (b) does not work as written. The status route is not asked for, and it is the biggest
single piece of scope. Counts: **1 blocker, 5 should-fix, 6 nit.**

---

## Hinge (brief item 1): which option for the Settings button

| Option | What it is | L3 (same as `/login`) | Can a test prove it without a real login? | Hazards |
|---|---|---|---|---|
| (a) `claude "/login"` (plan) | positional prompt | yes, if a slash command in the positional prompt is dispatched | The argv can be pinned by a unit test. **Dispatch can be proven by a harmless proxy:** `claude "/status"` (or `/help`) in a scratch pty. It goes through the same input path and changes nothing. The plan wrongly says only a real login can prove it (§4.7) | if logged out: onboarding login, then the queued `/login` runs again (S6) |
| (b) bare `claude`, then inject `/login`+CR once "ready" | L2 path reused | yes (same bytes) | Only with stubs. Real timing against real startup dialogs cannot be unit-proven | see B1: there is no ContextBar in that tab, and it can answer startup dialogs |
| (c) `claude auth login` | shell subcommand | **no**. CLI reference row: *"Use `--email` … `--sso` … and `--console` to sign in with Anthropic Console … instead of a Claude subscription"* (https://code.claude.com/docs/en/cli-reference). There is no in-TUI method picker. `/login`'s screen offers subscription / Console / 3rd-party (authentication docs) | yes. It is documented behaviour, so an argv pin is sufficient | needs a server-owned argv (about 10 lines in `open_pty`) |

**"Ready" in term_vt.py.** There is no single readiness signal. `inject()` composes two:
`_wait_for_quiescence` (`term_vt.py:4517`; 1.5 s quiet window, 8 s max, `:4371/:4385`) and
`_foreground_is_claude(pt.fd)` (`:4030`, `tcgetpgrp` + `ps -o comm=`). The resume "starting" state
(`pt.starting`, `:1431`, `_start_backstop`) exists only for `mode="resume"`.

Neither signal means "Claude's input box is focused." Typed too early, `/login`+CR lands in
whatever Claude is drawing first: the folder-trust dialog, the `ANTHROPIC_API_KEY` "use this key?"
prompt, or the first-run theme picker. The CR then accepts that dialog's default. That is a real
side effect: trusting `~`, or approving an API key.

**One Enter or two?** One is enough. The commands docs say *"Press `Enter` to run the highlighted
suggestion"* (https://code.claude.com/docs/en/commands, "How the command menu matches what you
type"). But `inject()` resends the CR up to 3 times when the body rows don't move within 0.4 s
(`:4405/:4411`, loop at `:4681-4690`). See N3.

**Recommendation: (a), with its proof moved first.** Before step 4 lands, run a proxy probe:
`claude "/status"` in a scratch pty. Pass means the `/status` panel renders, not a model reply.
It is non-mutating, but it does start a Claude process, so the orchestrator or the user decides
who runs it. If the probe fails, the fallback is **(c), with the user's explicit consent** to the
L3 deviation, **not (b)**.

---

## Findings

### B1 (blocker). The L1 proof is scheduled last, and fallback (b) does not work as written

1. **Defect.**
   - Plan §4.7 makes the user's step-7 click the only proof of L1, after steps 1-6 are built.
   - The fallback says "in `bootStandalone`, once `GET /api/term/attached` answers… inject `/login`… reuses the proven `/model` injection mechanism… ~20 lines". But the login tab is opened by `pickDirectory` **without `sid`**: `ext_launch.js:351-355` says *"`sid` is deliberately omitted … bootStandalone() already treats a missing ?sid= as 'no context bar'"*. And `ext_vt.js:4117` builds the ContextBar only `else if (sid)`. So in that tab nothing polls `/api/term/attached`, and nothing can inject.
   - Even with a poll, "attached + quiet" is true while Claude shows the trust, API-key or onboarding dialog. The injected CR would answer that dialog.
   - **Repro:** a logged-in user on a machine where `~` is untrusted clicks Settings, then Log in, under fallback (b). Actual: `/login\r` lands on the trust dialog, and Enter accepts "trust this folder". Expected: the login screen.
2. **Fix direction.** Prove the hinge before building the L1 UI, using a non-login proxy. Replace the fallback with (c), gated on user consent. Do **not** add `?login=1` or a standalone attached poll. Do not change L2.
3. **The way.**
   - Add step 0 to §4.5: "Probe: open a scratch pty and run `claude "/status"`. Pass = the status panel; fail = a model turn." Record the result in the plan file.
   - If it fails: in `open_pty`'s `mode == "new"` branch (`term_vt.py:3122-3128`), accept `body.get("action") == "login"` and set `argv = [gateway.launcher(gateway.ANTHROPIC), "auth", "login"]`, ignoring `prompt`. In `ext_cr_dialogs.js`, `openAt('~','new','', {gateway:'anthropic', action:'login'})`. `pickDirectory` would forward `opts.action` only when it equals `"login"`.
   - Classic and Control Room are not affected (L1 lives only in Control Room). Local and tunnelled callers are identical. The OpenRouter launcher is bypassed by `ANTHROPIC`.
4. **Test.**
   - (a) path: the existing step 2 pin.
   - (c) path, red first: in `tests/test_pending_pty_prompt.py::OpenPtyRoutePrompt`, `open_pty(h, None, {"mode":"new","cwd":tmp,"action":"login","prompt":"x"})` types exactly `claude auth login`, with no `x`. It is red before the branch exists, because the typed line is `claude x`.

### S1 (should-fix, but no code change). The L2 pill can approve a permission prompt

1. **Defect.** `inject()`'s guards are only quiescence plus `require_claude` (`term_vt.py:4662-4667`). A Claude permission prompt is quiet, and Claude is in the foreground. The bytes `^E ^U /login \r` reach the select list, and CR picks the highlighted default, "Yes". The CR can be resent up to 3 times. No server signal exists for "permission prompt pending": `waiting` covers only AskUserQuestion (`providers/claude.py:292`), and a grep for permission/approval detection finds none.
   - **Repro:** Claude is asking "Allow Bash(rm …)?" and the user clicks Log in. Actual: approved. Expected: nothing approved.
   - The same gap exists today for `/model` and `/effort` (`ext_vt.js:2424/2446`, `ext_cr_term.js:988`).
2. **Fix direction.** No new heuristic. A screen-scrape detector would be wider than this feature. Document it as a known gap, the same as base. Must NOT change `inject()`.
3. **The way.** Change the pill tooltip (both views) to: "Types /login into Claude. Use when Claude is idle at its prompt." Add one line in the PR body: "known gap, same as /model: an open permission prompt receives the Enter."
4. **Test.** None is possible without a real TUI. Add it to the human checklist (§ Human checks). The tooltip string can be asserted in the step 5 and step 6 tests.

### S2 (should-fix, but no code change). A multi-line draft is sent to the model with "/login" appended

1. **Defect.** `clear_first` sends Ctrl+E then Ctrl+U (`term_vt.py:4669-4675`). In a multi-line draft that kills only the current line. `/login` then no longer starts the message. The docs say *"A command is only recognized at the start of your message"* (commands page). So CR submits the user's half-written draft, plus "/login", as a model prompt. Even a single-line draft is erased without warning.
   - **Repro:** the user has typed 2 lines and not sent them, then clicks Log in. Actual: a model turn. Expected: the login screen.
   - The same gap exists for `/model` today.
2. **Fix direction.** Document it, same as base. Do not invent a "clear all" key sequence: Ctrl+C on an empty input is the first half of exit.
3. **The way.** The same tooltip and PR note as S1.
4. **Test.** Human check only.

### S3 (should-fix, scope). The status route is not asked for, and it is the largest piece of the plan

1. **Defect.**
   - The contract (L1-L3) asks for a control that *performs* `/login`. No clause asks to *display* login state. Plan §4.2 is the only new server code, plus a new test file and about half of step 4's cases.
   - Measured cost on this machine: `claude auth status --json` took **real 1.16 s, user 0.15 s**. That is wait-bound, probably the keychain. It is paid on every Server-tab render: `updateBlock`-style blocks `load()` on render, and the plan has no cache.
   - Network (conventions rule 6): in one sampled run (`lsof -i` every 0.1 s on the child pid), **no socket was observed**, and the exit code was 0. That is **not proof** that the CLI never refreshes a token.
   - The server's PATH and env are not the login shell's. A server started from an OpenRouter-exporting shell reports that env's `authMethod`, not the keychain login.
   - Keys returned today: `analyticsDisabled, apiProvider, authMethod, configDirectory, consoleProfileSignInOffered, email, loggedIn, loginExpiresAt, orgId, orgName, planTier, projectsDirectory, storedClaudeAiLogin, subscriptionType`. The plan's allowlist (read `loggedIn`, `authMethod` and `subscriptionType`, and build a fresh dict) holds if the CLI adds keys, because it never spreads `d`. That part is correct.
2. **Fix direction.** This is a user decision (DU2). Recommend **dropping** the status route and the Refresh button. Keep only the block's name, the one-line explanation and the Log in button. If it is kept, keep it exactly as designed (a local-only, allowlisted dict) and add nothing more.
3. **The way, if dropped.**
   - Delete step 1 and plan §4.2. `claudeLoginBlock()` loses `st`, `load()` and Refresh. It becomes `h('div',{class:'cr-cfg-row …'}, [name, sub, crBtn('Log in', login)])`.
   - Step 4's test drops the status cases.
   - `gateway.py` and `server.py` are untouched. There is no subprocess, no PATH question and no rule-6 question.
4. **Test.** If dropped, step 4's remaining cases still go red before the block exists. If kept, the plan's 5 cases stand. Add one: a stdout JSON carrying an unknown key `"newIdField":"SENTINEL"` must not appear in `json.dumps(result)`.

### S4 (should-fix). D3's OpenRouter hide is unreliable and probably not worth it

1. **Defect.** `meta.gateway` comes from the session's *model id*: `registry.py:93` sets `s["gateway"] = gateway_of(s.get("model"))`, and `gateway.py:17-20` returns `""` when there is no model. A fresh OpenRouter session has no assistant turn yet, so `gateway` is `""`, and the pill **shows**, contrary to D3.
   - The premise is also off. `/login` in that session still writes the machine-wide login (one keychain entry per config dir, per the authentication docs "Credential management"). It is not a no-op, only unused by *that* session, because `ANTHROPIC_AUTH_TOKEN` ranks 2 against `/login`'s 7 in the precedence list.
   - **Repro:** start "+ New Claude session" on OpenRouter, wait until the session is attached, before the first prompt. Actual: the pill is visible. Expected (per D3): hidden.
2. **Fix direction.** Recommend **dropping the hide** (DU3). Show the pill wherever Claude is in the foreground. That is the literal `/login`, and the simplest form of L3. If the user keeps D3, document the first-turn gap. Do not add a new server field for it.
3. **The way, if dropped.** Remove the `_applySessionData` edit (plan §4.3A last bullet) and the `st.gateway` term in `_syncStatusBar` (§4.3B). `el.loginPill.hidden = !st.attached;` then mirrors the model pill exactly.
4. **Test.** Drop the two "openrouter → hidden" cases. If D3 is kept, add the case "meta without gateway → visible" and document it as the known gap.

### S5 (should-fix). R3 under-reads the docs: a login is machine-wide, and one picker choice logs out the subscription

1. **Defect.** Plan R3 says that switching account is "not documented". The authentication docs say:
   - *"credentials are stored in the encrypted macOS Keychain … keys the macOS Keychain entry to that directory"*, i.e. one login per `CLAUDE_CONFIG_DIR`;
   - Console keyless sign-in at the `/login` prompt: *"What it signs you out of: Claude Code signs you out of any claude.ai login stored on the machine"* (https://code.claude.com/docs/en/authentication, "Sign in without an API key").

   So the method a user picks in a dashboard-launched `/login` affects every running session that shares the config dir.
2. **Fix direction.** Warn in one line. **Do not add a confirm dialog.** `/login`'s own method screen is already the confirm step (Esc cancels). A dashboard confirm would make the flow *differ* from the regular `/login` (L3), which is over-building.
3. **The way.**
   - The Settings block sub-line becomes: "Signs in for every Claude Code session on this machine. Opens Claude Code's own /login in a new terminal tab."
   - The pill tooltip gets the same first sentence.
   - Correct R3's text in the plan.
4. **Test.** Step 4 asserts that the sub-line contains "every Claude Code session on this machine". It is red before the block exists.

### N1 (nit). The step 6 harness is misdescribed

1. **Defect.** Plan step 6 says it reuses "the `ext_cr_term.js` node harness of `tests/test_cr_manage_terminals_parity.py`". That file is a brace-extractor (`_extract_function`, plus `_read_page`/`_extract_script_content`), not an executable harness for the `ext_cr_term.js` IIFE. `_onAction`, `_syncStatusBar` and `_injectSlash` are closure-private (`ext_cr_term.js:292`, `:1146`, `:988`).
2. **Fix direction.** Brief the implementer correctly.
3. **The way.** Extract `_onAction`, `_injectSlash` and `_syncStatusBar` with `_extract_function`. Stub `st`, `el` (with `modelPill`, `effortPill`, `loginPill`, `primaryGroup`), `post`, `j`, `showToast` and `window.ExtVT.ttyBody`, then run them under node.
4. **Test.** `_onAction("login")` posts `{text:"/login",submit:true,clear_first:true,require_claude:true}`. It is red, because the switch has no `login` case.

### N2 (nit). The slash menu has two matches for `/login`

`/login` also word-matches `/design-login` (commands page row and the "Highlighting" rule: *"from the start of the name or from a word within it"*). Enter runs the *highlighted* one. Exact-match ranking is not documented.
- **Fix:** none in code. Add a human check: after clicking, the login screen appears, not design-login.

### N3 (nit). The CR resend could auto-pick a login method

If the login screen takes more than 0.4 s to change the body rows, `inject()` resends the CR (`term_vt.py:4681-4690`). The extra CR selects the pre-selected method, so the user didn't choose it.
- **Fix:** none in code. A no-resend flag would be new server API for a small risk.
- **Human check:** the method screen waits for a choice.

### N4 (nit). Session-less terminals get no L2 pill

The Terminals tab, the launch pad's "+ New Claude session" and pending Resume tabs open without `sid`, so they have no ContextBar (`ext_vt.js:4117`). L2 is then absent exactly where a user might type `/login` by hand.
- **Fix:** document it as a known scope gap in the PR. Do not build a sid-less ContextBar for this.

### N5 (nit). The label sits beside the TRACKER_AUTH "Auth" row

The Server tab's first row is `Auth / TRACKER_AUTH` (`ext_cr_dialogs.js:1581`). "Claude account" right after it invites the exact confusion the user already corrected.
- **Fix:** name the block **"Claude Code login (/login)"**.
- **Test:** step 4 asserts that name.

### N6 (nit). Remote viewers would see a raw 403 (only if S3 keeps the status route)

A tunnelled viewer of the block would get `refused: request appears to be proxied (…)` as its status line.
- **Fix:** map `status === 403` to "Login status is shown on this machine only".
- **Test:** the plan's existing 403 case asserts the mapped text.

---

## Brief items answered without a separate finding

- **Item 2 (non-Claude PTYs).**
  - `require_claude` refuses a plain zsh, an Auggie resume and any non-`claude` foreground (`term_vt.py:4666`), and the pill is hidden there by `_setAttached`/`_syncStatusBar`.
  - Mid-turn: the spinner keeps the screen busy, so `inject()` returns "terminal never went quiet" after 8 s. That is a refusal, not a misfire.
  - Residual risk: a foreground `claude auth login` or `claude -p` also reads `comm == "claude"`. Edge case; not worth code.
- **Item 4 (remote, D4).** A terminal already passes the OAuth URL and code through the tunnel, and the auth code is single-use. The browser auto-opens **on the server Mac** (troubleshoot page, per the plan's R1 quote), so a remote user must use the URL shown in the pane and paste the code back. The plan's D4 default is acceptable. See DU4.
- **Item 7 (parallelism and bundle).**
  - Steps 1-6 are file-disjoint (checked).
  - There are no load-time references: `window.ExtLaunch` is read at click time.
  - No existing test asserts the `cr-term-status-right` markup (grep: none). `test_term_vt_client.py:496-561` asserts CSS selectors and the `vtswitchers` construction order. Neither breaks if a button is appended after `effortWrap`, but phone width (`ext_vt.css:405`) should be eyeballed with a third button.
  - Bundle: `server.py:9` already does `from .gateway import openrouter_configured`. Extending it is fine. `_AUTH_LABELS` and `AUTH_STATUS_TIMEOUT` collide with nothing (grep). HEADER has `json` and `subprocess`. All of this is moot if S3 drops the route.

---

## Human checks (only a real click proves these)

Run them in a logged-in session. **Press Esc at the method screen.** Nothing then changes.

1. **Settings → Server → Log in.**
   - A new tab opens and Claude's **login method screen** appears.
   - It is not a model reply, not "Unknown command" and not `/design-login`.
   - If a trust prompt appears first, note it; that is D1.
2. **Classic overlay** of a Claude session: the pill is visible only while Claude is foreground. Click it at an **idle, empty prompt** and the method screen appears, waiting for a choice (N3). Esc.
3. **Control Room terminal panel:** same as check 2.
4. **Pill on a plain shell terminal:** it is not shown.
5. (Optional, documents S1/S2.) Do not test with a live permission prompt on real work.

---

## Not examined

- The errors and troubleshoot page quotes in plan R1/R3 were not re-verified. The errors page fetch truncated at 100 KB.
- Real TUI behaviour of any option: barred.
- Whether the first-run or trust dialog defers a positional prompt.
- `scripts/bundle.py`'s handling of `gateway.`-qualified references in `term_vt.py`.
- The xterm and grid renderer differences for the pill.
- `claude auth status` behaviour when logged out (JSON on exit 1 is assumed by the plan).

---

## Clean-plan deltas

1. **§4.5:** insert **step 0, "Hinge probe"**: `claude "/status"` in a scratch pty, run by the orchestrator or the user (non-mutating, not a login). Steps 4 and 7 depend on it. Record the result in §2 R1.
2. **§4.7:**
   - Replace the "Fallback (no new route)" paragraph (`?login=1`, bootStandalone) with fallback (c): `body.action == "login"` → `argv = ["claude","auth","login"]` in `open_pty` `mode=="new"`, and the `openAt` opts forward `action:"login"`. It is used **only if the step 0 probe fails AND the user consents** to losing the method picker.
   - Delete "Primary verification … the only real login in the whole plan" as the *gate*. It becomes human check 1.
3. **§2 R3:** replace "Logging in to a DIFFERENT account … not documented" with the keychain-per-config-dir quote and the "signs you out of any claude.ai login stored on the machine" quote (S5).
4. **§4.2 and step 1:** mark as **optional, pending DU2**. Recommended: delete. If kept, add the unknown-key sentinel case and the 403 → "shown on this machine only" mapping (N6).
5. **§4.4:**
   - Block name "Claude Code login (/login)" (N5).
   - Sub-line "Signs in for every Claude Code session on this machine. Opens Claude Code's own /login in a new terminal tab." (S5).
   - If DU2 = drop: no `st`, no `load()`, no Refresh.
6. **§4.3 A and B:** tooltip "Types /login into Claude. Use when Claude is idle at its prompt. Signs in for every session on this machine." If DU3 = drop: remove the `_applySessionData` hide and the `st.gateway` term.
7. **§4.6 step 6:** replace the harness description with N1's extract-and-stub recipe.
8. **§4.6 steps 4 and 5:** add asserts for the tooltip, sub-line and block name. Remove the OpenRouter cases if DU3 = drop.
9. **PR body (step 7):** a known-gaps section covering S1 (permission prompt), S2 (multi-line draft), N2/N3 (menu match, CR resend) and N4 (session-less terminals). Plus the human checks above.

## Decisions the user must make

| # | Decision | Recommendation | Cost of the recommendation |
|---|---|---|---|
| DU1 | If the hinge probe fails: accept `claude auth login` (no method picker; Console only via a flag) for the Settings button? | **Yes, (c)**, rather than the inject-at-startup fallback | The Settings path loses the method picker. The in-terminal pill still gives the true `/login` |
| DU2 | Show login status in Settings at all? | **No. Drop the status route** | No at-a-glance state in Settings. The user sees it in the terminal or with `/status`. Saves the only server code, a subprocess per render (~1.1 s) and the network/PATH questions |
| DU3 | Hide the in-terminal pill on OpenRouter sessions (D3)? | **No, show it wherever Claude is foreground** | In an OpenRouter session the login is saved machine-wide but not used by that session |
| DU4 | Remote (tunnel + TRACKER_AUTH) use of the buttons (D4) | **Allow wherever terminals are allowed** (as planned) | A remote click opens a browser on the server Mac. The remote user must copy the URL and paste the code. The OAuth code transits the tunnel provider, as all terminal text already does |

D2 (no Log out button), D5 (no email) and D1 (cwd `~`) stand as planned. None is a new decision.
