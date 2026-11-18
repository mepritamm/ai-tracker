# Implementation review: Usage panel UI, Auggie and tests (adversarial)

Branch `usage-panel`, base 5e4b62d, commits 186c1f5, c6771ac, 3c9a943, 2bc7edf. Reviewer: opus, told to assume the
implementer's report is false. Scope: `aitracker/web/ext_cr_dialogs.{js,css}` (Usage tab, OpenRouter key row, Auggie
login row), `term_vt.py` (Auggie login argv, `_login_finished` kind gate, `_login_watch`), `providers/auggie.py`
(`month_cost`), and the new tests. Server-side guards (routes, key storage) belong to the security review. They are
touched here only where they decide what the UI shows.

**Counts:** blocker 0 · major 1 · minor 5 · nit 7.

## What I ran

- `node --check` on every `aitracker/web/*.js`: all pass. Assembled `page.build_page()`, extracted its 2 inline
  scripts and 1 style block. `node --check` passes on both scripts. The CSS has 1885 `{` and 1885 `}`, with no stray
  `*/` or `/*` outside comments. The tokens the new CSS uses (`--text-awaiting`, `--text-failed`, `--surface-sunken`,
  …) are defined with dark variants in `ext_cr.css`.
- All 11 new or changed test modules, one per process with `unset TRACKER_AUTH`, are green. `test_usage_ui` ran 18
  tests under node and none were skipped.
- **Live probe**, read-only: one `claude -p /usage` with the D2 flags. Only booleans and types were printed, no
  amounts. The logged-in account returned `limits` = 0, `extra_usage.is_enabled` = True, and types
  monthly_limit:int, used_credits:int, utilization:float, currency:str. **`utilization` matches
  `used/limit*100` (percent), not `used/limit`.** The plain-text report contains no money amounts, so it cannot
  confirm the cents scale. The scale rests on the research doc ("minor units of currency, cents for USD").
- **Real Auggie files** (the last 15, masked): `finishedAt` and `modified` are `YYYY-MM-DDTHH:MM:SS.mmmZ`, and
  `cost_usd` is a string. Both parse as UTC through `_ts_epoch` and `_iso_epoch`.
- **Red-proofs.** Mutated JS copies ran through `CR_DIALOGS_SRC`. Python mutations were scoped `sed` edits, restored
  with `git checkout -- <file>`.

| Mutation | Expected | Actual |
|---|---|---|
| `_login_finished`: `if claude:` → `if True:` | red | **red** (test_auggie_login_pty) ✔ |
| `month_cost`: drop `if mt < since: continue` | red | **red** (test_old_mtime_file_is_never_opened) ✔ |
| JS: credits block disabled (`if (s.credits)` → `if (false)`) | red | **red** (2 UsageTab failures) ✔ |
| JS: Auggie `onFocus` no longer removes itself | red | **GREEN**, false-green (m2) ✘ |
| JS: key input pre-filled via `value:` attribute | red | **GREEN**, cannot catch it (m3) ✘ |
| `auggie_usage`: month start in local time instead of UTC | red | **GREEN**, untested (m4) ✘ |

---

## M1 (major): the Claude card's account label and `sub` don't come from the run that produced the numbers

- **Defect.** `accounts.py:212-215`, `claude_usage()`, overlays `account` from `claude_auth_cached()` on every
  response. `_acct_claude_producer` (`accounts.py:203`) reads `sub` the same way. `claude_auth_cached()`
  (`gateway.py:140`) is filled only by `GET /api/claude/auth`, which only the Server tab calls (grep: its single
  caller is `server.py:523`). So the label is never tied to the account whose usage is shown:
  - **Repro 1 (fresh server).** Restart, then open Config → Usage first. Actual: the Claude card has no account line,
    and a team or enterprise credits login gets no "your organisation's limits apply" note, because `sub` is "".
    Expected: the logged-in account's label above its numbers.
  - **Repro 2 (the user's two accounts).** Open the Server tab while on the Max login, so the cache holds "Logged in ·
    Claude Max subscription". Switch to the credits login outside the tracker (`claude /login` in any terminal).
    Then Usage → Refresh, more than 60 s after the last run. Actual: the credits block renders under the header
    "Logged in · Claude Max subscription". Expected: the credits login's label, or a visible "last known" when the
    two can't be matched. Inside the 60 s floor, Refresh silently returns the old account's body.
- **Fix direction.** Stamp `account` and `sub` into the body inside the background run, so the label and the numbers
  come from the same moment. Show the body as stale when the current cached label differs from the stamped one.
  What must NOT change:
  - No `claude auth status` on the request thread.
  - No identity field beyond `label` and `subscription` (no email or org).
  - `_Bg` semantics stay as they are.
  - The Max (3 limits) and credits render paths stay unchanged.
- **Way.**
  1. In `_acct_claude_producer` (`accounts.py:172`), at the top, after the spec checks, call
     `st = claude_auth_status() or {}` (gateway's cached helper: at most 1 CLI run per 60 s, and it runs on the
     `_Bg` thread). Set `sub = st.get("subscription", "")`. Pass `account=st.get("label", "")` into both the `ok` and
     the `no_report` bodies. Add an `account` kwarg to `_acct_claude_body`, defaulting to "".
  2. In `claude_usage()`, keep `out["account"]` from the body. Only if the body has none, fall back to
     `claude_auth_cached()`. If the cached label is non-empty and differs from the stamped one, set
     `out["stale"] = True` (the UI already renders "(last known)").
  3. Import `claude_auth_status` bare. The bundle test forbids `accounts.` qualifiers in server.py, and a bare name
     in accounts.py is fine.
  4. Extend the rule-6 `/usage` exception text: "the background run also reads `claude auth status` through
     gateway's 60 s cache". The UI (`usageBlock`'s `accountOf`) needs no change.
- **Test** (`tests/test_accounts_claude_usage.py`):
  - Patch `accounts.claude_auth_status` to return `{"label": "Logged in · Claude Max subscription", "subscription":
    "max"}`. Run the producer on fixture A, then assert `body["account"] == that label`.
  - Patch it to `{"label": "L", "subscription": "team"}` and use fixture C. Assert the note is "your organisation's
    limits apply" even when `claude_auth_cached()` returns None.
  - Patch `claude_auth_cached` to return a different label. Assert `claude_usage()["stale"] is True`.
  - All three are red on the current code: no `account` in the producer body, the note is empty with a None cache,
    and there is no stale flag.

## m1 (minor): Save with an empty input silently clears the saved OpenRouter key

- **Defect.** `ext_cr_dialogs.js:1861`: `crBtn('Save', function () { save(input.value); })`. The server's validator
  `_v_or_key` (`config.py:249-254`) treats `""`, and whitespace once stripped, as "clear". Repro: key set → Replace →
  Save without typing. Actual: POST `{value: ""}`, the key is removed, and the status reads "API key: not set", with no
  confirm. Expected: nothing is sent. Clear asks to confirm (`:1865-1868`), but Save-empty skips that confirm.
- **Fix direction.** Refuse an empty or blank value from the editor on the client. What must NOT change: the Clear
  button still posts `""` after its confirm, and the server keeps "" = clear.
- **Way.** In `openrouterKeyBlock`, change the Save handler to
  `function () { if (!input.value.trim()) { msg = 'Paste a key first (Clear removes the saved key)'; paint(); return; } save(input.value); }`.
  `paint()` rebuilds an empty input, so nothing typed survives.
- **Test** (`tests/test_usage_ui.py` ServerTabBlocks): run `act: 'key'` with `firstBtn: 'Replace'` and `typed: ''`.
  Assert `posts == []` and "Paste a key first" in `afterSave`. Red now: one POST with `value: ""`.

## m2 (minor, test passes for the wrong reason): `test_focus_listener_removes_itself_after_close` can't go red for the Auggie block

- **Defect.** `tests/test_usage_ui.py:280-282` asserts `"focus" in removed`. The Server tab also builds
  `claudeLoginBlock`, whose own `onFocus` (`ext_cr_dialogs.js:1683-1686`) pushes `"focus"` into `removed`. Proven:
  deleting the `removeEventListener` from the Auggie `onFocus` (`:1833`) leaves the test **green**. It goes red only
  when the Claude block's removal is deleted too.
- **Fix direction.** Assert on the count, not on presence. No code change.
- **Way.** The harness already computes `out.left = (listeners.focus || []).length` after firing. Assert
  `r["left"] == 0` and `r["removed"].count("focus") == 2` (Claude and Auggie). Optionally record `focusBefore`
  before the close and assert it is 2.
- **Test.** That is the test itself. Red-proof: with the `A_nofocusremove` mutation (Auggie removal deleted),
  `left == 1` and the test goes red.

## m3 (minor, test can't catch it): the "never pre-filled" check misses an attribute pre-fill

- **Defect.** `tests/test_usage_ui.py:239-246` reads `input().value`. The fake DOM's `El` keeps `.value` as a
  separate property: `setAttribute('value', x)` sets only `attrs.value`. A regression such as
  `h('input', { value: peek.x, … })` pre-fills a real browser input, because the attribute is the default value, yet
  the test stays **green** (proven with the `B_prefill` mutation). Today the server sends no key, so this is a guard
  gap, not a live leak.
- **Fix direction.** Assert the attribute is absent too. No code change.
- **Way.** In `_BODY`, add `vattr: input().attrs.value` to `out.inputAttrs`. In the test, assert
  `"vattr" not in r["inputAttrs"]`. JSON drops `undefined`, so the existing equality already fails if `vattr` is
  ever set: add the field and keep the `assertEqual`.
- **Test.** As above. Red with the `B_prefill` mutation.

## m4 (minor, untested): the UTC month start of the Auggie window is never asserted

- **Defect.** `accounts.py:358` computes
  `since = datetime(now.year, now.month, 1, tzinfo=utc).timestamp()`. Mutating it to local time
  (`datetime(now.year, now.month, 1).timestamp()`) leaves `tests.test_auggie_month_cost` **green**. Every stamp in
  `AuggieUsageBody` is "now", and the `MonthCostTests` pass `since` explicitly. D3 (UTC month to date) has no
  guard. The code is correct today.
- **Fix direction.** Pin the window boundary. The code stays as it is.
- **Way.** Add a test that patches `accounts.month_cost` with a spy and freezes `datetime` in `accounts` (or factors
  `_acct_month_start(now)` out). Assert `since == calendar.timegm((Y, M, 1, 0, 0, 0))` for a `now` early on the 1st
  UTC, for example 2026-12-01T02:00Z, where IST local time is already the 1st but a local midnight would be 5.5 h
  earlier.
- **Test.** As above. Red under the local-time mutation.

## m5 (minor): a no-limit credits login renders an empty 0% bar

- **Defect.** `ext_cr_dialogs.js:1757`: `usageBar(s.credits.utilization, 'normal')`. For fixture C (team or
  enterprise, `monthly_limit: null`), `_acct_credits` returns `utilization: null` (`accounts.py:156-157`), and
  `usageBar` draws a 0%-width track. Repro: a credits body with the text "$12.34 spent this month · no monthly limit
  of its own" and `utilization: null`. Actual: an empty bar under it, which reads as "0% used". Expected: no bar,
  since there's no limit to measure against. A related point: the credits bar is always `is-normal`, even at 95%.
- **Fix direction.** Draw the bar only when `utilization` is a number. Optionally colour it by threshold, but only if
  the server sends a severity (rule 5: never derive thresholds in JS). The text and note stay unchanged.
- **Way.** Change the bar argument to `typeof s.credits.utilization === 'number' ? usageBar(s.credits.utilization,
  s.credits.severity || 'normal') : null`. Server-side severity is optional and out of scope for this fix.
- **Test** (`test_credits_block_renders_server_text_only_when_present`): for the `nolimit` body, assert
  `len(r["fills"]) == 0` (no other bars, because `limits` is []). Red now: one `width:0%` fill.

## Nits (direction stated; none blocks)

- **n1.** `usageCard` Refresh (`:1725`) and the Auggie `onFocus` (`:1832-1835`) reset `tries` and call `load()` while an
  earlier poll chain may still be pending. That gives two chains at once and doubled GETs until `refreshing` clears.
  Direction: keep a `timer` handle, and call `clearTimeout(timer)` before a new `load()`. Test: Refresh during
  `refreshing`, then count GETs.
- **n2.** The `openrouterKeyBlock` header comment (`:1841-1843`) says the input is cleared "after every save attempt
  that is not a 400". The code also clears it on a 400 (`:1882`), as the plan wants. Direction: fix the comment, not
  the code.
- **n3.** Cancel (`:1862`) drops the editor but leaves the typed key in the detached `input` closure until the next
  edit. Direction: `if (input) input.value = ''; input = null;` in Cancel. Hygiene only, not visible.
- **n4.** `_acct_money` (`accounts.py:140-142`) divides by 100 for every currency, which is wrong for zero-decimal
  ones such as JPY. Only USD has been observed. Direction: no change now; note it next to the D2 / 3b record. If a
  non-USD account appears, map the exponent per ISO 4217.
- **n5.** The non-inline fallback of the Auggie login goes through `ext_launch.js:373`, which toasts "Starting a new
  Claude session". The same happens for the Claude login. Direction: pass `opts.toast` or suppress the toast for
  login prompts. Cosmetic.
- **n6.** The Auggie "ended" toast reports the current status. After a declined or failed Switch account, while the
  old login is still valid, it says "Auggie: Logged in · Augment …", which can read as success. Auggie has no outcome
  record, by design (plan §4). Direction: wording only, for example "Auggie: login terminal closed · <label>". No
  code-level fix is needed.
- **n7.** `month_cost` accepts `cost_usd: true` as $1 (`float(True)`), while `parse_auggie` (`auggie.py:669-672`)
  does the same. Bool is never seen in real files (all are str). Direction: no change. Both paths agree, which
  is the seam that matters.

## Verified OK

- **XSS:** every new DOM node is built by `h()` with string children, which become text nodes
  (`ext_cr_dialogs.js:53-56`). There is no `html:`, and every `innerHTML` assignment is `= ''`. The toast title and
  meta are text nodes (`:280-284`). The `style` width is a clamped number, and the severity only reaches `className`.
- **Polling:** each card polls only while it is in the DOM (`isConnected`) and at most 60×3 s. A tab switch
  (`body.innerHTML=''`) or a dialog close (`wrap.remove()`) stops it. A pending timeout re-checks before it loads.
- **`crReadOnly()`:** `usageBlock`, `auggieLoginBlock` and `openrouterKeyBlock` all return null, the Usage tab shows
  "Usage is shown on this machine only.", and a 403 shows per-card text with no Set/Replace buttons.
- **Key row:** a password input with `new-password` autocomplete and no name or id. No response value is ever
  written into it, it is cleared after every save, and the status comes from `?peek=1` only (test asserts the bare
  route is never fetched).
- **Max path:** 3 rows with labels, percents, `is-<severity>` bars and the "active" tag, and no credits block
  (`test_probed_max_shape_three_rows_no_credits`).
- **Credits path:** 0 rows and the credits block. "No plan limits reported" is suppressed. The mutation goes red.
- **Both together:** 3 rows plus credits.
- **Money and percent math:** cents per the research doc. The live probe confirms `utilization` is already a
  percent, so the bar width is right. A null limit never renders "Unlimited".
- **Load-time safety:** `node --check` passes per file and on the assembled page, the CSS braces and comments
  balance, and the new code is definitions only (no top-level calls). The node harness evals the whole
  `ext_cr_dialogs.js` without throwing.
- **Auggie login argv:** the fixed `auggie auth login --headless` on any gateway, the prompt is only a selector
  (never typed), and a missing auggie returns 400 with no spawn.
- **Auggie login pty:** it uses the dedicated pty and is hidden from terminal lists and from `resolve_spawned`
  latching (`term_vt.py:2225`, `:2388`, `:4494`). `_login_watch` applies (1800 s, above the 600 s OAuth timeout).
- **Kind gate:** `_login_finished` writes `last_login.json` only for `claudeai` and `console` (red-proof went red),
  and invalidates `auggie_auth` for Auggie. Nothing under `~/.augment` or `~/.claude` is deleted or edited.
- **Imports:** `term_vt.py` is not in the bundle `ORDER`, so its lazy relative imports
  (`from .agent_cli import _agent_spec`, `from .accounts import usage_invalidate`) are safe.
- **`month_cost`:** a file with mtime < since is never opened (red-proof went red). The per-exchange `finishedAt`
  (UTC `Z`) is used, falling back to `modified`. Sub-agent cost is counted by `modified`, as stated in the note.
  Non-numeric costs go to `unpriced`. The cache is keyed by (path, mtime, since) and capped at 4000 entries.

`git status` after the review: clean apart from this file. Every red-proof edit was restored with
`git checkout -- <file>`, and mutated JS copies stayed in `/tmp/upr`.
