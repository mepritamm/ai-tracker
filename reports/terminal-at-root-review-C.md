# Adversarial re-review C: plan v3 (terminal-at-root)

Reviewer: opus. Read-only. I used grep and sed ranges only. Base: this worktree @ `76bd154`.
Scope: (1) did the 13 reconciled fixes actually land in v3; (2) new defects v3 introduced; (3) anything
earlier reviews missed. I did not re-argue the user decisions or E1-E3.

## 1. Are the 13 reconciled fixes in v3?

| # | Present in v3 | Correct against code | Note |
|---|---|---|---|
| 1 | yes (`Pty.run_dirs`, `_folder_retype` keeps it, retry test) | yes. `_refresh_fg` 1876-1881 clears only `fg`; `_folder_retype` 2405-2411 rebuilds the claim, so a dict on the Pty survives | the `""` key has a staleness nit (C3) |
| 2 | yes (never bracket in `_inject_argv`, CR/LF refused) | yes. 1950 is the only bracketing call in `_inject_argv`; `inject()` is untouched | ok |
| 3 | yes (`sh -c` form) | **the shape is right but the launcher resolution is wrong.** See C1 | |
| 4 | yes (2075/2109/2123, 2499/2556, 2149/2203, SPA 2925/3851) | yes. A grep of `t.cwd` in `web/` finds no other terminal-row matcher. `ext_cr_dialogs.js` 2052/2069 and `ext_vt.js` 2643/2658 are labels only, and they want the run dir | ok |
| 5 | yes (`recorded_run_dir` preference) | yes in `term_vt`, but its parse fallback recurses when called from `registry` (C2) | |
| 6 | yes (place before the 404, all modes, both paths) | yes | ok |
| 7 | yes (E1 open) | n/a | ok |
| 8 | yes (real `Screen`, `INJECT_MIN_WAIT` patched) | yes | ok |
| 9 | yes (counts, any claimant) | mostly. The 50 ms bound is flaky under the planned load re-run (C4) | |
| 10 | yes (relative gitdir, realpath) | yes | ok |
| 11 | yes (`shlex.quote`, then the AppleScript escape) | yes. The nested quote of `inner` inside `sh -c` round-trips | ok |
| 12 | yes | yes | ok |
| 13 | yes (`test_swap_in_types_cd_line`) | yes | ok |

## 2. Findings

### C1. MAJOR: `shutil.which` under the server's PATH changes which `claude` runs

**Defect.**
- Plan lines 204-206 (`_inject_argv`) resolve `launcher = shutil.which(argv[0])` in the server process.
- Today `gateway.launcher` (`gateway.py:43-44`) returns the bare `"claude"`. The folder shell resolves it through the **user's login-shell PATH** after the rc files run.
- The server's PATH can differ: it may be started from launchd, from a non-login `make serve`, or with a pyenv/nvm/npm-global PATH. Then `which` returns a *different* binary (for example an old `/usr/local/bin/claude` from npm while the user runs `~/.local/bin/claude`). It does not return None.
- Risk 3 ("which misses → bare name") covers only the miss case, not the wrong-hit case.

**Repro.** The server runs with `PATH=/usr/local/bin:/usr/bin`, and `/usr/local/bin/claude` is an old npm 1.x. The user's zsh PATH puts `~/.local/bin` first.
- Actual: the typed line execs `/usr/local/bin/claude --resume S` (the old CLI) for worktree sessions only.
- Expected: the same `claude` that a non-worktree resume gets today.

**Why the resolution buys nothing.** It does not restore aliases or functions: `exec "$@"` skips them either way. `sh`'s `exec` already does the PATH search with the PATH the login shell exported.

**Direction.**
- Pass `argv[0]` through unchanged (bare `claude`, or the already-absolute OpenRouter launcher).
- Do not resolve it server-side.
- Do not change the dedicated or overflow `spawn` path.

**Way.**
- In `_inject_argv`, build `line = "sh -c 'cd \"$0\" && exec \"$@\"' " + shlex.join([rd] + argv)`.
- Delete the `shutil.which` step at the route.
- Delete inventory row 20's "new `shutil.which`".
- Delete Risk 3's "safe and tested" claim.
- Keep the L0a(b) `type claude` check, which documents the alias gap.

**Test.** `TestOpenPtyAtRoot.test_typed_line_keeps_bare_launcher`: patch `shutil.which` to return `/wrong/claude`, then assert that the typed line ends `… '<top>' claude --resume <sid>` and never contains `/wrong/claude`. It is RED with v3's resolution. It replaces v3's "which → None gives a bare token" test, which cannot catch the wrong-hit case.

### C2. MAJOR: infinite recursion, `registry.parse_any` → `place` → `recorded_run_dir` → `registry.parse_any`

**Defect.**
- Plan lines 189-190 call `term_gate.place`/`home_note` from inside `registry.parse_any` (172).
- `recorded_run_dir` step 2 (plan 146-147) falls back to `registry.parse_any(sid)["meta"]` whenever the tail has no `cwd`, that is, when the final line is over 96 KB (a large tool result is common).
- `parse_any` has no re-entrancy guard and no memo on this path (`registry.py` 172-190).

**Repro.** A Claude transcript whose last line is 120 KB, then `GET /api/session?id=S`.
- Actual: `RecursionError`, a 500 on every ~2 s detail poll.
- Expected: the meta, with `term_home`.

**Direction.** Placement must never call `parse_any` when it is called from inside `parse_any`. `term_vt`/`term_launch` keep their fallback.

**Way.**
- Give `place(sid, cwd, mode, meta=None)` and `recorded_run_dir(sid, meta=None)` an optional `meta` argument.
- When `meta` is given, the fallback reads `meta["cwd"]`/`meta["gitBranch"]` instead of calling `parse_any`.
- `registry.parse_any` passes its own `meta`.
- Same for `home_note`.

**Test.** `TestRegistryTermHome.test_huge_last_line_no_recursion`: a fixture whose final line is 120 KB, then `registry.parse_any(sid)` returns a dict with `term_home`. It is RED (RecursionError) without the `meta` pass-through. The existing L1 test `test_tail_empty_falls_back` exercises only the term_gate entry, so it would not catch this.

### C3. MINOR: a stale `run_dirs[""]` mislabels an idle root shell

**Defect.**
- Plan 198-199: `_run_dir(p, sid=None)` uses `(p.fg or {}).get("session", "")`. When `fg is None` that is `""`, and the `""` key is a `new` claim's entry, never cleared.
- After a `new` in worktree W exits, the idle root shell reports `cwd = W` in `_live_list`/`_term_title`.
- `resolve_spawned` then scans W for every later poll, and a later `new` from worktree W2 overwrites the entry.

**Repro.** `new` in W, claude exits, then `GET /api/term/list`.
- Actual: the row shows `cwd == W`, title W.
- Expected: `cwd == root` (the shell is idle at the root).

**Direction.** Consult `run_dirs` only for an explicit sid or a live claim. Keep the "never cleared by `_refresh_fg`" property for retries (fix 1).

**Way.** `_run_dir(p, sid=None)`: if `sid is None` and `p.fg is None`, return `p.cwd`; otherwise use `p.run_dirs.get(sid if sid is not None else p.fg.get("session", "")) or p.cwd`.

**Test.** `test_live_list_idle_after_new_reports_root`: set `run_dirs={"": W}` and `fg=None`, then assert that `_live_list` gives `cwd == root`. It is RED with v3's formula.

### C4. MINOR: L2c's 50 ms lock-hold bound flakes under the planned parallel load run

**Defect.**
- Plan 324 asserts a max `_LOCK` hold under 50 ms. The review step (341-342) re-runs L2c with 2-3 module processes in parallel.
- A thread can be descheduled while it holds the lock. Under GIL plus CPU contention, holds of 50-100 ms happen even when no slow work runs under the lock.
- The known-flaky `term_vt` backstop is the precedent.

**Repro.** Run L2c alongside two other test modules on a loaded laptop. Actual: an occasional hold of about 60-80 ms fails the test. Expected: it fails only when a spawn is held under the lock.

**Direction.** Keep the RED proof, and widen the margin between the pass bound and the fail case.

**Way.** Make the fake spawn sleep 0.5 s and assert a max hold under 0.2 s. The RED proof (spawn moved under `_LOCK`) then fails at ≥0.5 s.

**Test.** The same test. Run it 20× under `stress`-like load and expect green. With spawn under `_LOCK` it is RED.

### C5. NIT: run v3's fg-detection claim in L0a, not just argue it

Evidence 3 (plan 87-89) is correct in reasoning.
- `sh` is the job leader, `exec` keeps the pid, so comm becomes `claude`, and `_foreground_is_claude` (`term_vt.py` 4060-4075) reads the pgid leader's comm.
- `_refresh_fg` compares `_fg_pgid(pt) != pt.pid` (1874), which is unaffected.

L0a(a) already checks "fg pgid comm == claude". Add `_foreground_is_claude(fd)` returning True as an explicit L0a assertion. Otherwise there is nothing to change.

## 3. Missed by both earlier reviews

- **C1 and C2** above.
- The external path's inner `( … || … )` chain has no `exec`, so `sh` stays the leader. That is harmless, because external tabs are never fg-polled. Say so in the PR notes.

## Overall clean plan (delta to v3)

- **L2b:** drop `shutil.which`; the typed line keeps `argv[0]` verbatim (C1).
- **L2b:** `_run_dir` returns `p.cwd` when `sid is None and fg is None` (C3).
- **L2a/L2b:**
  - `place`/`recorded_run_dir`/`home_note` take an optional `meta`;
  - `registry.parse_any` passes its own (C2).
- **L2c:** spawn sleeps 0.5 s and the hold bound is 0.2 s (C4).
- **L0a:** assert `_foreground_is_claude` is True (C5).
- **Tests:**
  - add `test_typed_line_keeps_bare_launcher`;
  - add `test_huge_last_line_no_recursion`;
  - add `test_live_list_idle_after_new_reports_root`;
  - remove the "which → None" test.
- **Docs:** inventory row 20 and Risk 3 lose their `which` text.

## Not examined

- `_swap_in` internals beyond the claim.
- The Auggie `meta.cwd` shape.
- macOS `p_comm` for a symlinked launcher (unchanged from today either way).
- The phone layout of `term_home_note`.

## Verdict: READY WITH NITS

C1 and C2 are major but small and local, and their fixes are designed above. Fold them in, plus C3-C5, before L2b starts. No re-plan is needed.
