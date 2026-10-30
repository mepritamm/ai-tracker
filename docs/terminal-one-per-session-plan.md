# One session ⇒ one terminal, + idle TTL knob

Branch `worktree-term-one-per-session` (worktree `.claude/worktrees/term-one-per-session`, base 594ac65).

## Contract (verbatim)
1. "remove them, simply it just by keeping the overflow section and add a ttl of 30 minutes after inactiveness, add a config for the same in the ai-tracker as well"
2. "keep the sharing of folder terminals but removing/dropping the design where overflow gets 1 and folder gets 1 that mean each agent session gets 2 terminals at 1 go, thats pretty annoying"
3. "go ahead with recommended, yes drop overflow labels and the folder labels, just a minor change where you have the config for terminal ttl to have it in minutes instead of seconds in the config box."

Recommended decisions accepted: a DIFFERENT session in a busy folder shell still gets its own dedicated pty; an idle Claude at its prompt with no viewer IS reaped at the TTL.

| Clause | Status |
|---|---|
| One session never gets two terminals (folder + overflow) | not discharged |
| Folder-terminal sharing kept | not discharged |
| Idle TTL, 30 min default, configurable | not discharged |
| TTL shown/edited in minutes | not discharged |
| Overflow + folder labels dropped from the UI | not discharged |

## Root cause (opus review)
- RC1: `open_pty` spawns a fresh folder `$SHELL -l`, claims it idle at T≈0, `_inject_argv` waits ≤8s (`INJECT_MAX_WAIT`) for the prompt; slow rc (pyenv rehash stalled 60s by stale `~/.pyenv/shims/.pyenv-shim`) ⇒ timeout ⇒ falls through to a dedicated "overflow" pty, leaving the just-spawned folder shell with `session=S1`. Two terminals.
- RC2: resume never dedupes against a dedicated pty already running that session.
- TTL: `IDLE_TIMEOUT=1800` hardcoded; `_reader` touches `last_active` on every output chunk, and Claude's footer redraws on a timer, so Claude ptys are never idle-reaped.

## Plan
- **A (term_vt.open_pty)**
  - **B:** `_session_pty(sid)` dedupe. A resume attaches to a live pty already running that sid (folder fg or dedicated).
  - **A:** when this request just spawned the folder shell, return it immediately. A daemon thread `_deferred_folder_start` waits ≤`FOLDER_STARTUP_WAIT=120` for the prompt, then injects (+ backstop on resume). On failure it feeds a note and NEVER spawns a second pty. The reused-shell path is unchanged.
- **Config:** `TERM_IDLE_TTL_MIN` (minutes, default 30, clamp 1–1440), env `TRACKER_TERM_IDLE_TTL_MIN`, in EDITABLE/VALIDATORS/_RESOLVERS/_PLAIN_ATTR_KEYS (live, no restart). Control Room Terminal tab slider in minutes. README line.
- **TTL:** `term_vt` drops `IDLE_TIMEOUT`, reads `config.TERM_IDLE_TTL_MIN * 60` late-bound in `_reader`. Activity = body output (not Claude's footer band) + keystrokes + viewers.
- **Labels:** drop the `[overflow]` tag/badge/notice and the folder badge/title from `web/ext_vt.js` + `web/ext_cr_dialogs.js` and the notice in `term_vt.py`. The internal `Pty.folder`/`Pty.overflow` flags stay (they drive reap/close).

## /tracker-gap framing
- **Capability:** opening a session's terminal yields exactly one terminal, the folder shell is still shared, and idle terminals close after `TERM_IDLE_TTL_MIN` minutes.
- **Asymmetry:** the fresh-folder-shell path (slow rc) vs the reused-shell path. The first one double-spawns.
- **Seam:** `term_vt.open_pty` + `_reader`, which are provider-agnostic; every launch flows through them. The setting goes on the shared `config` → `/api/config` → Config dialog path. The labels live in the one terminal-row renderer.
- **Consumers:** server `/api/term/*` + `/api/config`; client `ext_vt.js` row + `ext_cr_dialogs.js` Terminal tab, on every viewport, with no host gating.
- **Evals:** unit tests per leg, plus an integration eval (`tests/test_integration.py`) that boots the server and asserts the setting round-trips via `/api/config` and that the served page has the slider and no `[overflow]` tag.

User follow-up (verbatim): "implement the plan with /tracker-gap and do an adversial review for the implementation. If everything is fine, run the /tracker-push"

User follow-up (verbatim): "incase the adversial review found real issues in the review then have the opus plan the fix and get it going."
→ Loop: opus review → (real issues) opus fix plan → sonnet fixers → opus re-review → clean ⇒ /tracker-push.

## Head-out contract (user answers, 2026-10-29)
User note (verbatim): "make sure you dont assume too much and make decisions on behalf of me"
- Push: /tracker-push → `personal` only (advisor360 archived), only after a clean opus re-review.
- Live check: worktree server on a separate free port, stopped by PID; never touch the user's :8787.
- Product-decision findings: fix the clear bugs, PARK the judgment calls and HOLD the push.
- Delete the stale `~/.pyenv/shims/.pyenv-shim` (user-approved).
- My own defaults (reversible): slider range 5–240 min vs validator 1–1440; one branch, one commit per leg.

## Progress
- [x] Leg 1 (sonnet): open_pty dedupe (`_session_pty`) + deferred folder start (`_deferred_folder_start`, `FOLDER_STARTUP_WAIT=120`) + overflow notice → None. Tests proven red by revert. test_folder_terminal 22, test_term_vt 322, test_term_vt_exec 107 OK. Side-fixes: Thread.start failure guard; test_term_vt ~3750 patches `_inject_argv`.
- Commits: a single commit after the review (the commit hook runs the full gate each time).
- [x] Leg 2 (sonnet): config knob + Config slider (5–240 min) + labels drop + README + tests — test_cr_routes 22, test_term_vt_client 259, test_term_vt_exec 107, parity 17 OK; selfcheck `_run()` ok
- [ ] Leg 3 (sonnet): `_reader` TTL late-bound + footer-aware activity + TestIdleTimeout
- [x] Leg 3 (sonnet): `_reader` reads `config.TERM_IDLE_TTL_MIN*60`, `_note_activity` footer-aware touch, TestIdleTimeout + 3 new, integration `TestTermIdleTtlEndToEnd`.
- Review A (opus, open_pty): REFUTED.
  - F1 HIGH: a fresh shell reads idle at t≈0, so the deferred wait is skipped; slow rc ⇒ "claude was not started" at ~9.5s, plus a mid-rc type variant that can still give 2 terminals.
  - F2 MED: a stale folder `fg` ⇒ a resume attaches to a bare shell (regression).
  - F3 MED: `FG_PENDING_GRACE` is measured from the claim, not from the type.
  - F4 LOW-MED: two near-simultaneous opens ⇒ folder + overflow.
  - F5 PRODUCT DECISION (PARKED, holds push): `_session_pty` attaches to forked copies / trusts the `spawned` latch; `resolve_spawned(throttle=0)` costs ~0.6s per resume.
- Review B (opus, TTL/config/labels): REFUTED.
  - B-F1 MED: a folder row is titled by the opener `t.session`, not the fg (regression).
  - B-F2 MED-LOW: `_footer_anchor_band` false-positive on `─` rule prompts ⇒ shell progress bars stop counting (regression).
  - B-F3 LOW: flaky `test_ttl_change_applies_without_restart`.
  - F7 nits.
  - PARKED (user's call, holds push): B-F4 reaping an idle Claude kills its background tasks/subagents; B-F5 slider 5–240 vs validator 1–1440; B-F6 unproven against a real Claude byte stream (verifying needs a real claude run = token cost).
- [x] Fixer B (sonnet): B-F1 (folder row titled by fg only), B-F2 (`_foreground_is_claude` gate in `_note_activity`), B-F3, F7. test_term_vt 326, test_term_vt_exec 109, test_term_vt_client 259, parity 19, test_integration 104 OK; selfcheck ok.
- [x] Opus fix plan for F1–F4 (`_folder_settled`, `_inject_argv(deferred=)`, grace re-stamp, `Pty.startup_done`, `_session_pty` refresh; 13 tests). Residuals: rc `read` prompt; narrowed mid-rc typing.
- [x] Fixer A (sonnet): F1–F4 per plan; test_folder_terminal 33 (3x), test_term_vt 326, test_term_vt_exec 109, test_resume_fork_session 26 OK. Added `_join_deferred_starts()` in 5 test_term_vt tests.
- Re-review A (opus): F1–F4 HOLD; real shell types once after ~4s.
  - New N1 LOW-MED: an unsettled cwd shell the user typed into gets claimed ⇒ fix `keys()` sets startup_done.
  - Known gaps: F1a narrowed (document); F1b rc `read` prompt (PARKED, user's call).
- Re-review B (opus): B-F1/B-F2/F7 HOLD.
  - R1: touch-before-_act_v race.
  - R2: `ps` fork per pty every ~5s ⇒ probe only when the band looks like Claude.
  - R3: parity nit.
  - Observation: TTL 1 min < 120s startup wait (extreme setting only).
- [x] Fixer N1 (sonnet): `keys()` sets `startup_done` on a folder pty (term_vt.py:3346); `TestUnsettledShellWithUserInputOverflows` red→green; test_folder_terminal 34 OK x3.
- [x] Fixer R1–R3 (sonnet): touch-before-_act_v; ps probe only when the band looks like Claude (`test_plain_shell_activity_never_forks_ps` red→green); parity assertIn.
- Final quiet gate (haiku):
  - 77 modules, 2162 tests, 0 fail; test_term_vt 327 OK on a solo re-run after a 137; selfcheck ok; node --check clean on all 8 JS files; TestIdleTimeout 3/3.
  - FLAKE: `test_job_after_settle_retries_with_claim_still_pending` failed 1 of 2 ([True] != [True, True]) ⇒ widening its timeline (sonnet).
- [ ] Deflake → commit → /branch-sync → (after parked decisions) /tracker-push

## Parked for the user (push held)
1. F5: `_session_pty` attaches a resume to a forked copy / trusts the `spawned` latch; `resolve_spawned(throttle=0)` adds up to ~0.6s per resume click.
2. B-F4: reaping an idle Claude (no viewer, 30 min) also kills its background tasks/subagents/loops and its unsent draft.
3. B-F5: the slider is 5–240 min, but the validator/env accept 1–1440.
4. B-F6: TTL behaviour unverified against a real Claude byte stream (verifying = a real claude run, which costs tokens).
5. F1b: an rc `read` prompt (oh-my-zsh update [Y/n]) receives the typed resume line.
6. COMMIT BLOCKER (pre-existing on main, outside the plan): `term_vt.py:2407`/`:2530` (main 2363/2486) run `os.killpg(os.getpgid(pid), SIGKILL)` right after `pty.fork()`. Before the child's setsid, `getpgid` returns the PARENT's group (253/300 measured), so it SIGKILLs the test runner (the hook's `test_term_vt` rc=137 at `test_3b_abandoned_swap_does_not_leak_the_replacement_child`) or, in production, the tracker server's own group. Fix way: a `_kill_fresh_child(pid)` helper that killpg's only if `pg != os.getpgrp()`, then `os.kill(pid)`, plus the same guard in `Pty.kill()`. Red test: patch getpgid → getpgrp, assert killpg is never called with the own group. Staged, not committed.
### User decisions on the parked items (2026-10-30)
- #6 kill bug ⇒ fix in this branch.
- #2 B-F4 ⇒ keep a Claude pty alive while child processes run (background work counts as activity).
- #1 F5 ⇒ narrow the scan: probe only new-mode candidates, exclude forked ptys from `_session_pty`.
- #3 B-F5 ⇒ keep the 5–240 slider and add help text that env/config.json allow 1–1440.
- #4 B-F6 ⇒ run the real-Claude check (small token cost approved).
- #5 F1b ⇒ separate handover: `docs/handover-rc-read-prompt.md` (pick up after this lands).

### Real-Claude check (B-F6), done 2026-10-30 — HOLDS
- Setup: claude v2.1.314 `--model haiku`, 120x40, real `term_vt.spawn`/`_reader`.
- Idle: the anchor band is constant at 6 and fg is claude. `_body_rows_version` changed once (startup draw), then stayed flat for 58.7s ⇒ reaped at the TTL.
- Working (a 45s foreground Bash): the body version changed on every 0.5s sample for ~50s ⇒ kept alive.
- Notes:
  - An idle Claude barely redraws, so footer exclusion is only weakly exercised here (the synthetic test covers it).
  - Model-call silences of ~10s exist (≪ the 1 min minimum TTL).
  - `_foreground_is_claude` blips False for one sample during a tool (harmless: it over-counts).
  - The trust dialog defaults to "No, exit".
- Artifacts: ~/.claude/jobs/3513f2df/tmp/realcheck/.

### Plan C (opus) → sonnet implementer → opus review
- Implemented:
  - `_kill_group(pid)` (no more killpg of our own group; test_term_vt ran 3x full, no SIGKILL).
  - `resolve_spawned(new_only=)` + `_session_pty` skips forked.
  - `_claude_work_children`/`_claude_busy` keep-alive.
  - Slider help text.
- Review: changes 1/3/4 HOLD; change 2 REFUTED: every plain-shell reap forked `ps -o comm=` (stalls 12s+ under load ⇒ the idle-reap flake). Fix: `_claude_busy` checks `_footer_anchor_band` first (sonnet fixer).
- Documented trade-offs:
  - A Claude with a live `run_in_background` job stays open until it exits.
  - Skipping forked dedicated ptys means a second resume of a live background agent can make a second fork copy.
  - The folder `forked` flag is sticky (still one terminal via the same-cwd peek).
  - `term_run.py:323` `Job.kill` keeps the old `killpg(getpgid)` pattern (low risk, out of scope).

Documented gaps (no change): F1a narrowed mid-rc typing; TTL at 1 min < 120s startup wait.
- Docs: CLAUDE.md worktree section + tracker-gap Step 0 now require `/branch-sync` before every push (global CLAUDE.md rule 5 and the `gap` skill already said so).
- Baseline gate (haiku, pre-fix): 76/78 modules OK, 1819 tests, 0 fail; selfcheck ok; node --check clean. `test_term_vt` OOM-killed 137 twice (ran under concurrent agent load) — UNPROVEN, must re-run quiet.
- [ ] Final gate (haiku): per-module, quiet, after all fixes
- [ ] Adversarial review (opus)
