# Terminal at the repo root: one shared shell per repo, faster opens (plan v4)

Durable file (rule 4). Base: `personal/main` @ `76bd154`, worktree `.claude/worktrees/terminal-at-root`,
branch `worktree-terminal-at-root`. Status: **PLAN v4 ONLY. No code. Implementation waits for the user
("Stop at the plan").** Author: plan agent (opus). Line numbers were re-read in THIS tree. Other agents
are editing `tests/`/`aitracker/` here for unrelated base-gate fixes, so **re-read every cited line
before editing** (conventions rule 12).

**Changelog**
- v1: root only for sessions with a `worktree-state` record.
- v2: the user's decisions (any git worktree, both buttons, both paths); shell at the root, claude in a
  `cd` subshell; concurrency section; async inventory.
- **v3: folds every "Fix taken" of the reconciliation (rows 1–13, below) into the legs.** The changes:
  - `run_dir` moves to `Pty.run_dirs` (1);
  - no bracketed paste, and CR/LF is refused (2);
  - the shell-agnostic `sh -c` form with a resolved launcher (3);
  - the missed call sites, including dropping the SPA shortcut (4);
  - the run dir is the worktree top, preferring worktree evidence (5);
  - placement happens before the 404 in every mode and on both paths (6);
  - E1 stays open (7);
  - test fixes (8, 9);
  - relative gitdir and realpath (10);
  - no leak to the wire, and quoting (11);
  - check ordering and inventory rows (12);
  - a takeover test (13).

  E1–E3 stay open.
- **v4: the user decided E1–E3 (2026-11-16).**
  - E1: a removed worktree is reported by a server-owned message, and a one-click confirm
    **recreates** it (§A2: branch rules, per-path lock, edge cases, a drafted rule-6 exception); then
    the SAME session id is resumed in it.
  - E2: subshell for every session (already the v3 design; the alternative is dropped).
  - E3: S3 is now a leg (L5). A cold open execs claude at once in a dedicated pty while the root shell
    warms; resume/new openers never wait on a warming shell.
  - Review C fixes C1–C5 are folded into the body as well (launcher unchanged, `meta=` with no
    recursion, `_run_dir` only while claimed, 0.5 s / 0.2 s lock bound, the L0a foreground check).

- **v4.1: review D folded (verdicts at the end).**
  - The branch comes from the transcript's `gitBranch`. The fallback base is the default-branch tip,
    never the checkout HEAD, and the confirm says so (D1).
  - The admin entry is found by `gitdir` content; prune runs only when the target path is still
    registered; the sibling-reflog loss is PR-noted (D2).
  - A lost cross-process race counts as success (D3).
  - The rule-6 text is tightened; `_valid_recreate_path`; an HMAC, single-use, 10-min token (D4).
  - The confirm gets an `openGen`/`stillCurrent` guard, a toast fallback and a lazy `window.ExtVT` (D5).
  - S3: atomic slot reservation, a dedicated-session reuse test and the warm-shell settle timeout (D6).
  - A re-clone test (D7). C1 is restated in §A.

## Contract (verbatim)

| # | Clause (verbatim) | Verdict |
|---|---|---|
| 1 | "when I resume any session, is it possible to resume that session from that repo folder itself, instead of the worktree the session is working on, such that any other session when I resume it for that, can utilise that very prior opened terminal as well" | not discharged |
| 2 | "is it possible to spin up the terminal for the root repo folder instead of the worktree, and try to utilise it more such that we can have them quickly, use async a lot across the entire app, build out the plan and review and implement the chain from claude.md" | not discharged |
| 3 | "implement and plan via /tracker-gap and then /tracker-push" | not discharged |
| 4 | Sign-off: "Stop at the plan" | being honoured: plan only |
| 5 | Async scope: "1 and surface what else isnt async and what are the ones that isnt async yet and can be async" | not discharged (inventory in §C is the "surface" half) |
| 6 | Root rule: "2 and make sure open terminal and resume both the buttons should open at the root repo folder not at the worktree" | not discharged |
| 7 | Push/testing: "test this behaviour and plan and review this in a manner such that it doesnt hold up when running multiple sessions at once" | not discharged |
| 8 | E1: "Push a message about the worktree being removed and mention that the new 'Opne terminal' or 'Resume' will create a new worktree for this session, I believe creating a new session with the old session's context can be generated or that session can create a new worktree for the continuation of the work" | not discharged (§A2) |
| 9 | E2: "Subshell for every session (Recommended)" | not discharged (§A; L2b) |
| 10 | E3: "Include S3" | not discharged (L5) |

## User decisions (2026-11-15)

Recorded verbatim, with how each is read:
- **Sign-off.** "Stop at the plan". No implementation until the user returns.
- **Async scope.** "1 and surface what else isnt async and what are the ones that isnt async yet and can
  be async". In scope: terminal open plus a few clear wins (S1, S2, plus whatever concurrency needs).
  Also a complete inventory (§C).
- **Root rule.** "2 and make sure open terminal and resume both the buttons should open at the root repo
  folder not at the worktree". Applies to ANY git worktree (not only `.claude/worktrees/` or recorded
  ones), to both Open terminal and Resume, in-app and external.
- **Push.** "test this behaviour and plan and review this in a manner such that it doesnt hold up when
  running multiple sessions at once". Concurrency section and tests (§B).

## User decisions (2026-11-16)

Recorded verbatim, with how each is read:
- **E1.** "Push a message about the worktree being removed and mention that the new 'Opne terminal' or
  'Resume' will create a new worktree for this session, I believe creating a new session with the old
  session's context can be generated or that session can create a new worktree for the continuation of
  the work". Read as:
  - the server reports the removal (detail note plus route response, every viewport, both launch paths);
  - Open terminal / Resume / New then recreate a worktree for the session;
  - the **same** session id resumes in it (claude finds the transcript by id), so no new session is
    needed (§A2).
- **E2.** "Subshell for every session (Recommended)". The `sh -c 'cd "$0" && exec "$@"'` form is used
  for every worktree session, recorded or not.
- **E3.** "Include S3". Leg L5.

## Capability in one line

Every terminal for a session in a git worktree opens in **one shared shell at the main checkout root**.
A Resume or New-Claude is typed into it as `sh -c 'cd "$0" && exec "$@"' <worktree top> <launcher> …`, so
Claude always runs in the worktree and never in the primary checkout, whether or not Claude Code recorded
the worktree.

### Asymmetries
- **Claude vs Auggie.** Root resolution is git-file reading and provider-agnostic, so Auggie's Open
  terminal also opens at the root. The worktree-evidence preference (row 5) is Claude-only, because only
  Claude transcripts carry `cwd` history and `worktree-state`. Resume is Claude-only on both tiers, as
  today.
- **Server vs client.** The server decides the directories, the note and the error. The SPA renders
  `meta.term_home_note` and the route `error` (rule 5). The client's cwd-matching shortcut is removed
  rather than re-derived (row 4).
- **In-app PTY vs external Terminal/iTerm.**
  - In-app: one long-lived root folder shell, shared.
  - External: every click is a new tab (nothing to share). It opens at the root, and resume runs through
    `sh -c` in the worktree. When Claude exits, the tab is left at the root. The `sh -c` form also fixes
    today's `( … )` chain for a fish login shell.
- **localhost vs remote/phone.** External stays localhost-only (`server._local_caller`). The in-app path
  is identical over the tunnel. A 409 `error` renders on every client through the existing error paths:
  `ext_vt.js` 2985-2997, `ext_launch.js` 63-71, `ext_cr_term.js` 563.

## Evidence (measured or read in this tree)

1. **Linked-worktree layout.**
   - `<wt>/.git` is a file: `gitdir: <G>`. The gitdir may be relative (git ≥2.48
     `worktree.useRelativePaths`).
   - `<G>/commondir` holds `../..`. `<G>/gitdir` holds `<wt>/.git`.
   - `git rev-parse --git-common-dir` costs 58 ms (a subprocess). Reading the files costs microseconds.
   - Submodules have no `commondir`. Bare repos have a common dir not named `.git`. Both stay unmapped.
2. **The bare-resume-from-root hazard.** 18 of the 62 sessions here that last ran under
   `/.claude/worktrees/` have no `worktree-state` record. A bare `claude --resume` from the root runs them
   in the primary checkout.
3. **Foreground detection.** `_foreground_is_claude` (4018) reads the comm of the foreground pgid leader.
   With `sh -c '… exec "$@"'`, sh is the job leader (pid == pgid) and then execs claude, so comm is
   `claude`. The parent shell never `cd`s, so `_swap_candidate`'s `_shell_cwd` check (3421) still holds.
4. **Claim lifetime.** `_refresh_fg` sets `pt.fg = None` (1880) when the job exits. That is before the
   fork/attach backstop retypes (`_folder_retype` 2382, claim rebuilt at 2411), so per-job state is lost
   at exactly the retry.
5. **Bracketed paste.** `_inject_argv` writes `_bracket_if_needed(...)` (1950). That wraps the line at
   ≥ `INJECT_BRACKET_LEN_THRESHOLD` = 200 chars (4404/4561). macOS `/bin/bash` 3.2 does not understand
   bracketed paste.
6. **Open-route ordering.** `cwd`/`new` call `session_cwd(sid)` with no walk, and both routes 404 before
   any placement (`term_vt.py` 3088-3091, `term_launch.py` 194-198). With `resume=True`, the walk on a
   deleted `.claude/worktrees/x` lands on `<root>/.claude/worktrees`, which is inside the primary repo's
   tree (`term_gate.py` 90-95).
7. **S1.** The cold `parse_any` in `session_cwd` (71) takes 5.63 s on an 11 MB transcript; `_tail_scan`
   takes 0.001 s. `term_run.py` 470 benefits too.
8. **S2.** In the Screen branch of `_wait_for_quiescence`, `last_change = start` (4530), so every warm reuse
   waits at least 1.5 s. `INJECT_MIN_WAIT` = 0.3 (4365) floors the best case. The no-Screen branch already
   measures from `last_output` (4541).
9. **S3.** A fresh login shell takes 11.2–13.5 s here.
10. **`_LOCK`.** No fork, subprocess or sleep runs under it on the open path; both reviews verified this.
    The only cross-request wait is `pending.wait(FOLDER_SPAWN_WAIT=3.0)` (3166). Waiters wake at
    `reserved.set()` (3187), before the claim, so **any** of K openers may win the claim. `MAX_TERMS`
    defaults to 12.

## Design

### A. Directory policy (single server seam)

**`aitracker/util.py`** (next to `_git_branch` 89, which is left as is; its relative-gitdir bug goes in the
PR notes). Pure file reads that never raise:
- `git_worktree_root(path) -> (root, wt_top)`, or `("", "")`.
  1. Walk up from the existing `path` to the first dir `D` with a `.git` entry.
  2. Require `.git` to be a file `gitdir: G`. Set `G = normpath(join(D, G))` when G is relative.
  3. Require `G/commondir`. Set `C = normpath(join(G, read(commondir)))`.
  4. Require `basename(C) == ".git"` and `isdir(dirname(C))`.
  5. Return `(realpath(dirname(C)), realpath(D))`.

  A main checkout, a plain dir, a submodule or a bare repo gives `("", "")`.
- `deleted_worktree_root(raw) -> str`, for a **missing** `raw`. Take the nearest existing ancestor `A` and
  the first ancestor `T` of `A` that has a `.git` **directory**. Return `realpath(T)` when either:
  - (a) some `T/.git/worktrees/*/gitdir` (resolved relative to its own dir) names `raw` or an ancestor of
    `raw` plus `/.git`, or
  - (b) `raw` starts with `T/.claude/worktrees/`.

  Otherwise return `""`.

**`aitracker/providers/claude.py` `_tail_scan`** (89): before the `message` `continue`, harvest:
- `cwd` (latest);
- `cwds` (distinct, newest first, capped at 16);
- `wt` (the latest `worktree-state` `worktreeSession`, with null clearing it to `None`, plus a
  `wt_seen` flag);
- `gitBranch` (latest).

These are added to the returned dict. The 5-tuple `_tail_fields` is untouched.

**`aitracker/term_gate.py`:**
- `recorded_run_dir(sid, meta=None) -> (raw, branch)` (C2: when `meta` is passed, by `parse_any`, the
  fallback uses it and never re-enters `parse_any`). Claude sids only (`registry.provider_for(sid).prefix == ""`);
  anything else gives `("", "")`. Steps:
  1. `path = claude.find_session(sid)`, `t = _tail_scan(path)`.
  2. If `t["cwd"]` is empty (a single line longer than 96 KB, or no transcript), fall back to
     `registry.parse_any(sid)["meta"]` (`cwd`, `gitBranch`).
  3. The row-5 preference, in this order:
     - `wt_seen` and `wt` set: `raw = wt["worktreePath"]`.
     - `wt_seen` and `wt` None (ExitWorktree): `raw = latest cwd`, as the session deliberately left.
     - No record: `raw =` the newest entry of `cwds` whose `git_worktree_root` is non-empty, else the
       latest `cwd`. When that newest worktree entry no longer exists, it is the deleted case (below).

  Safe direction: a later bare-root cwd never beats earlier worktree evidence.
- `session_cwd` (71): S1 fast path. The tail `cwd` is tried first, with a `parse_any` fallback when it is
  empty. The ancestor walk is factored into `_existing_ancestor(path)`, shared by `place` (rows 6/E1,
  never duplicated). Existing stubs and tests are unchanged.
- `place(sid, cwd, mode) -> {"shell", "run", "note", "error"}`. Order (row 12): **resolve worktree →
  existence check → placement**. `cwd` is whatever the route's `session_cwd` lines returned, possibly
  `""`. Steps:
  1. `raw, branch = recorded_run_dir(sid)`. When `raw == ""` (fake test sids, Auggie), use `raw = cwd`.
  2. If `raw` exists and `(root, top) = git_worktree_root(raw)` is non-empty:
     `shell = root`, and `run = top` for resume/new or `None` for `cwd` mode.
  3. Else if `raw` is missing and `root = deleted_worktree_root(raw)`: the **E1** branch (decided). All
     three modes return `{"recreate": plan}` (§A2) instead of a shell. The route answers **409** with
     `{"error": <server message>, "recreate": plan}`. Nothing is launched and nothing is written until
     the confirmed retry. If `isdir(root)` is false, there is nothing to recreate into: §A2 "repo gone".
  4. Else (not a worktree, or a main checkout): `shell = run = cwd`, today's behaviour byte for byte.
  5. If `shell` is empty and there is no `error`, the route 404s as today.
- `home_note(sid, cwd, meta=None) -> str` and `place(..., meta=None)` take the same optional `meta`
  (C2). `home_note` uses the same functions. It is used by `registry.parse_any`.

**Call sites (row 6: placement before the 404, all three modes, both paths):**
- `term_vt.open_pty` (2951), session form, replacing the 404 at 3090-3091:
  - `pl = term_gate.place(sid, cwd, mode)`.
    - If `pl` has `recreate`: when the body's `recreate` token matches, run
      `term_gate.recreate_worktree(pl["recreate"])` and then `place` again; otherwise answer 409 with
      `{error, recreate}`.
    - Return 409 on `pl["error"]` and 404 if `not pl["shell"]`.
    - `term_launch.open_terminal` does the same.
  - Then `cwd = pl["shell"]` and `run_dir = pl["run"]`.
  - The folder lookup, spawn and claim then key on the root.
  - **Overflow** (3306): `spawn(run_dir or cwd, argv, …)` for resume/new. A `cwd`-mode overflow shell
    stays at the root.
- `term_launch.open_terminal` (159): the same replacement of 196-198.
  - `build_script(cwd=pl["shell"], sid, mode, app, resume_argv, run_dir=pl["run"])`.
  - With a `run_dir`, resume becomes `cd <q root> && sh -c <q inner> <q run_dir>`, where
    `inner = 'cd "$0" && (' + chain + ')'` and `chain` is the existing
    `(<resume> || <attach> || <fork>)` built from `shlex.quote`d tokens.
  - Every path goes through `shlex.quote` first and then the existing AppleScript escape at 81-85
    (row 11).
- `registry.parse_any` (172), every provider, next to `resume_cmd` (266-274):
  `meta["term_home"], meta["term_home_note"]` from `term_gate.place`/`home_note`. No subprocess.

**`aitracker/term_vt.py`, run-dir plumbing (rows 1, 2, 3, 4, 11, 13):**
- `Pty.__init__` (1385 area): add `self.run_dirs = {}`, mapping sid to the worktree top (`""` key for a
  `new` claim). It is written under `_LOCK` and **never cleared by `_refresh_fg`**. Writers:
  - the open_pty claim (3229): `fp.run_dirs[sid if mode == "resume" else ""] = run_dir`;
  - `_swap_in(fp, cand, sid, argv, forked, cols, rows, run_dir=None)` (3449; caller 3346 passes it);
  - `_folder_retype` keeps the dict entry when it rebuilds the claim at 2411.
- `_run_dir(p, sid=None) -> str`: with an explicit `sid`, `p.run_dirs.get(sid) or p.cwd`. With no sid,
  `p.run_dirs.get(p.fg["session"])` **only while a claim exists**, else `p.cwd` (review C3: a stale
  `run_dirs[""]` from an earlier `new` must never label an idle root shell).
- `_inject_argv(pt, argv, deferred=False, sid=None)` (1917):
  - `rd = _run_dir(pt, sid)` read under `_LOCK`. Callers pass `sid`: 3276, 3615, 2428, 3487. The default
    `None` keeps `(pt, argv)` test stubs valid.
  - If `realpath(rd) != realpath(pt.cwd)`, build `line` as
    `"sh -c 'cd \"$0\" && exec \"$@\"' " + shlex.join([rd, launcher] + argv[1:])`. Here `launcher` is
    `argv[0]` exactly as `gateway.launcher` returns it (review C1: no `shutil.which`, because the
    server PATH can pick a different `claude`), and sh's exec resolves it through the login shell's PATH.
    **C1, restated: the typed line, the dedicated-pty argv, the external `build_script` chain and the
    post-recreate resume all use that same unresolved `argv[0]`. Nothing in this feature calls
    `shutil.which`.**
    Otherwise `line = shlex.join(argv)`.
  - **Refuse** `"\n"`/`"\r"` anywhere in `line` with `(False, "unsafe path")`.
  - **Never bracket**: write `line.encode()` instead of `_bracket_if_needed(...)`. `inject()` keeps its
    bracketing.
  - Shell aliases and functions named `claude` are skipped for worktree sessions only. This goes in the PR
    notes.
- Missed call sites (row 4):
  - `resolve_spawned`: `forked_cwds.add(...)` (2075) adds `_run_dir(p)` and every value of
    `p.run_dirs` for forked ptys. `newest_session_in_cwd(p.cwd …)` (2109) and the claim comparison (2123)
    use `_run_dir(p)`.
  - `store.record_fork(sid, …)` (2499, 2556): pass `_run_dir(pt, sid)` only when non-empty. A session that
    moved cwd mid-run keeps today's first-cwd mismatch.
  - `_term_title` folder (2149) and `_live_list` `cwd` (2203): use `_run_dir(p)`. The row gains
    `"shell_cwd": p.cwd`. `_fg_public` (1884) is unchanged: `run_dirs` is a Pty attribute and never
    reaches the wire, and only the current `cwd` (run dir) does (row 11).
- SPA (row 4): delete the `mode === "cwd" && targetCwd && t.folder && t.cwd === targetCwd` clause in
  **both** copies (`web/ext_vt.js` 2925 and 3851). The server answers `reused: true`, and a client match
  could peek a shell that another session holds. The now-unused `targetCwd` lookups (2904-2909,
  3834-3839) go with it.

No config knob. `resume_cmd` and the session-less `{cwd}` picker form are unchanged.

### A2. A removed worktree: report it, then recreate it on one-click confirm (E1; v4.1 with review D folded)

**Message (server-owned, every viewport, both launch paths).**
- Before the click: `registry.parse_any` sets `meta.term_home_note` (L4 renders it in the CR terminal
  header and classic `#ext_launch`) to: *"Worktree `<path>` was removed. Open terminal or Resume will
  recreate it (`<plan.summary>`) and continue this same session there. Uncommitted changes from the old
  worktree cannot be recovered."*
- On the click: the 409 body carries the same text in `error`, plus `recreate`.
- The note is computed **without git** (file reads only; `test_no_git_on_poll`). The git probes run only
  when building the 409 plan.

**How a worktree is normally removed (review D1 evidence, git 2.54).** `git worktree remove` deletes the
admin entry `G` (its `HEAD` and `logs/HEAD`) at once. That is what the cleanup skill, the pending-work
worker and ExitWorktree all use, and the pending worker also `branch -d`s the branch. `G` survives only
a hand `rm -rf`, and only until the next `worktree prune`/auto-gc. **So the admin entry is a bonus
source, never the primary one.**

**Plan (`term_gate.recreate_plan(sid, raw, root, meta=None) -> dict | None`).** It writes nothing and
returns `{path, branch, new_branch, base, base_kind, summary, token, expires}`.
1. **Validate the target** with `_valid_recreate_path(raw, root) -> bool`:
   - `realpath(raw)` equals the session's recorded run dir (`recorded_run_dir`);
   - it is outside `root`'s own work tree, or inside `root/.claude/worktrees/`;
   - `dirname(raw)` already exists (git would `mkdir -p` the parents);
   - it is not `/`, `$HOME` or `root` itself.

   If validation fails, the answer is a plain 409 message with **no `recreate` key** (D4).
2. **Re-check the repo (D7).** `root` must exist and `git_worktree_root`-style reads of `root/.git` must
   succeed. The plan is not bound to stale admin data: every SHA is verified with
   `git cat-file -e <sha>^{commit}` against the **current** repo, so a re-cloned repo at the same path just
   falls through to the default-base rule.
3. **Branch `B`, primary source:** the transcript's latest `gitBranch` (`_tail_scan`, or `meta`).
   Optional bonus: the admin entry `G`, **located by content, not by basename** (D2):
   `term_gate._admin_dir_for(root, path)` scans `<root>/.git/worktrees/*/gitdir` for content equal to
   `<path>/.git` (relative content is resolved against `G`). git appends digits on name collisions, e.g.
   `api` and `api1`. When `G` is found, `G/HEAD` may confirm or replace `B` (it wins only if the
   transcript has no `gitBranch`).
4. If **`refs/heads/B` exists and is not checked out in another live worktree**:
   `git -C <root> worktree add <path> B` (same path, existing branch). `base_kind = "branch"`.
5. If **B exists but is checked out elsewhere**: `git -C <root> worktree add -b <B>-cont-<sid8> <path> B`.
   `base_kind = "branch-tip"`.
6. If **B is gone** (deleted after merge, or removed): a new branch `<B or worktree-<basename>>-cont-<sid8>`.
   The base is the first that verifies:
   - (i) `G/logs/HEAD` last new-sha, if `G` survived (hand-deleted worktree): `base_kind = "last-commit"`;
   - (ii) **the default-branch tip** from `_default_base(root)`: `git symbolic-ref --quiet
     refs/remotes/origin/HEAD`, else the first existing of `refs/remotes/*/main`, `refs/heads/main`,
     `refs/heads/master`, `refs/heads/develop`. `base_kind = "default-branch"`.

   It is **never the primary checkout's arbitrary `HEAD`** (D1). If none of these exist, the answer is
   409 with no `recreate` key ("no base branch found — recreate the worktree by hand"). A SHA is never
   guessed.
7. Collision on `<B>-cont-<sid8>` gives `-2`, `-3` and so on. Names are checked with
   `git check-ref-format --branch`.

**What the user sees in the confirm** (`summary`, built server-side, capped at 300 chars for phone):

| `base_kind` | summary text |
|---|---|
| branch | "Recreate `<path>` on branch `B` (your work on B is intact)." |
| branch-tip | "`B` is checked out at `<other>`; recreate `<path>` on new branch `B-cont-xxxxxxxx` from B's tip." |
| last-commit | "Branch `B` was deleted; recreate `<path>` on new branch `B-cont-xxxxxxxx` from its last commit `<sha7>`." |
| default-branch | "Branch `B` was deleted (likely after merge) and its last commit is not recoverable here; recreate `<path>` on new branch `B-cont-xxxxxxxx` from `<default>` `<sha7>`. Commits from B are only present if they were merged into `<default>`." |

When a prune is needed, the summary appends: "Also clears N stale worktree registration(s) (their old
commit pointers are lost)."

**Token (D4: single-use and short-lived; HMAC costs about 8 lines of stdlib, so it is in).**
- A module-level `_SECRET = secrets.token_bytes(32)` per server process.
- `exp = now + 600`.
- `token = "%d.%s" % (exp, hmac.new(_SECRET, f"{sid}|{path}|{branch}|{new_branch}|{base}|{exp}".encode(), "sha256").hexdigest())`.
- Verification: `hmac.compare_digest`, `exp > now`, and the token not in `_USED_TOKENS`, a set pruned of
  expired entries on every insert and guarded by the recreate module lock. The token is added on the
  first use.
- A mismatched, expired or reused token gets a **re-plan** (409 with a fresh plan), never a write.
- A token from the other server process (8787 vs 8790) fails verification and simply re-plans.

**Why a one-click confirm, not automatic.**
1. It **writes to the user's repo**: a new dir, a new branch ref, possibly a prune. This app's stance is
   read-only, so a write must be visible and intended.
2. The trigger buttons sit on the board, in the rail, on phone and behind the tunnel, where a stray tap
   is easy. A silent git write from a mis-tap is the worst failure here.
3. Rules 5 and 6 make choices (new branch name, base) the user should see, especially the
   `default-branch` fallback.
4. One click is cheap. Automatic would save one tap on a rare path.

So the flow is: 409 with plan, then confirm with the server's `error` + `summary`, then the same POST
with `{"recreate": token}`.

**Execution (`term_gate.recreate_worktree(plan) -> (ok, path_or_err)`).** It runs in the confirmed
request's own handler, never under `term_vt._LOCK`:
- **Per-path lock:** `_RECREATE_LOCKS[realpath(path)]` (dict guarded by a module lock), blocking
  acquire with a 30 s timeout. It is in-process only, and that covers the external and in-app routes of
  **one** server, since both call `term_gate`. Two server processes (8787 plus 8790) are covered by the
  D3 rule below, not by a cross-process file lock (that would be overbuilt).
- **Inside the lock, re-check first:**
  - path now a live worktree of `root` (`git_worktree_root(path)[0] == root`): proceed with no git work;
  - path exists but is **not** a worktree: **refuse** (409 "path occupied by a non-worktree directory;
    move it or resume elsewhere"). Never write into it;
  - token invalid: re-plan, 409.
- **Git commands** (exact allowlist, `-C <root>`, env stripped of `GIT_DIR`/`GIT_WORK_TREE`/
  `GIT_INDEX_FILE`/`GIT_COMMON_DIR`, `timeout=30`):
  - read-only probes `rev-parse --verify --quiet refs/heads/<b>`, `worktree list --porcelain`,
    `cat-file -e <sha>^{commit}`, `check-ref-format --branch <b>`, `symbolic-ref --quiet
    refs/remotes/origin/HEAD`, plus plain file reads of `.git/worktrees/*/{gitdir,HEAD,logs/HEAD}`;
  - `git worktree prune` **only when the target path is still registered-but-missing** (found by
    `_admin_dir_for`), because git 2.54 refuses `worktree add` on such a path without `-f`, which is
    banned. Prune is repo-wide by git's design: sibling hand-deleted worktrees lose their admin reflog.
    **Accepted and PR-noted** (D2; the snapshot alternative was rejected as overbuilt). The summary
    counts them;
  - then exactly one of `git worktree add <path> <B>` or `git worktree add -b <new> <path> <base>`.

  **Never `--force`/`-f`, never `-B`, never `branch -D`, never `reset`/`checkout`/`clean`.**
- **Lost the race (D3).** If `worktree add` fails **and** the path is now a live worktree of `root` on
  `plan.branch` or `plan.new_branch` (another process won), treat it as success. Otherwise surface git's
  stderr, capped at 300 chars. Only one re-check, no retry loop.
- On success, `place` re-runs and finds a live worktree: shell at the root, then
  `sh -c 'cd "$0" && exec "$@"' <path> <argv[0] as gateway.launcher returned it> --resume <sid>` (C1).
  The **same session id** is resumed; claude finds the transcript by id.

**Edge cases.**
- **Branch deleted/merged:** rule 6 (last commit if hand-deleted, else the default-branch tip, with the
  honest summary).
- **Branch checked out elsewhere:** rule 5.
- **Path occupied:** refuse.
- **Path outside the repo or with a missing parent:** no plan (D4).
- **Repo gone:** 409 "repository `<root>` no longer exists — resume by hand (`claude --resume <id>` from
  any folder)", with no `recreate`.
- **Re-cloned repo at the same path:** stale SHAs fail `cat-file -e`, so the default-branch base applies
  (D7).
- **git missing or failing:** stderr surfaced; nothing launched.
- **Concurrent clicks:** at most one `worktree add` per server (lock), and a cross-process loser resumes
  (D3).

**Confirm wiring (D5).** One helper in `web/ext_vt.js`:
`window.ExtVT.confirmRecreate(body, retry, stillCurrent)`.
- It shows `window.confirm(body.error + "\n\n" + body.recreate.summary)` and measures how long it took.
- If the answer is false and it took **< 50 ms** (confirm suppressed: iOS standalone PWA, sandboxed
  iframe), it shows the server text through the existing toast/notify instead, so the click is never a
  silent no-op.
- On true it calls `retry({recreate: body.recreate.token})` **only if `stillCurrent()`**.

Call sites resolve **`window.ExtVT` lazily at click time**: `ext_vt.js` is concatenated last
(`page.py` 17), so a module-scope capture in `ext_cr_*`/`ext_launch` would be `undefined`.

| Entry point | Status source | `stillCurrent` |
|---|---|---|
| `ext_vt.js` `_openVTFresh` (2932) | its `{ok,status,j}` | `() => gen === openGen` (gen captured before the confirm) |
| `ext_vt.js` `mountInto` (3660 area) | same | same openGen guard |
| `ext_launch.js` `openTerm` (60) | `r.status` and `await r.json()` on non-ok (already parsed at 62) | `() => cur === sidAtClick` |
| `ext_cr_term.js` `_openExternal` (via `j()` 49, keeps status) | `res.status`/`res.j` | `() => st.sessionId === sidAtClick` |
| `ext_cr_boot.js` answerSession (`postTermOpen` 785, keeps status) | same | `() => true` (a one-shot board action) |

**Gate: never from a read-only or tunnel-visitor request (D4.5).** Both routes already sit behind
`term_gate.guard` plus the read-only 403 (`server.py` Handler gate). L2d adds an explicit assertion that a
recreate POST from a read-only/tunnel visitor gets 403.

**Conventions rule 6: a documented exception is required.** Drafted text for
`.claude/rules/conventions.md` rule 6, added in L2d, tightened per D4:

> *"Exception (terminal worktree recreate, user-requested 2026-11-16): `aitracker/term_gate.py`
> `recreate_worktree()` — and only it — may write to a git repository, and only on an explicit user
> confirmation: a POST to `/api/term/pty` or `/api/term/open` carrying a recreate token that this server
> process issued (HMAC over session id, path, branch, new-branch flag, base and expiry), valid for at most
> 10 minutes and accepted once. Never on a poll, list or page load, and never from a read-only or tunnel-
> visitor request. The target `<path>` must be the realpath this session's transcript records (its cwd or
> `worktree-state.worktreePath`), must lie outside `<root>`'s own work tree or inside its
> `.claude/worktrees/`, must not exist (or be a live worktree of `<root>`, in which case nothing is run),
> and its parent directory must already exist. It never creates missing parent directories. It runs in
> the session's own main checkout (`git -C <root>`, with `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`/
> `GIT_COMMON_DIR` removed from its environment, 30 s timeout each), and only these commands: the
> read-only probes `rev-parse --verify --quiet refs/heads/<b>`, `worktree list --porcelain`,
> `cat-file -e <sha>^{commit}`, `check-ref-format --branch <b>` and `symbolic-ref --quiet
> refs/remotes/origin/HEAD` (plus plain reads of `.git/worktrees/*/{gitdir,HEAD,logs/HEAD}`);
> `git worktree prune` only when the target path is registered but missing; and exactly one of
> `git worktree add <path> <branch>` or `git worktree add -b <new-branch> <path> <base>`. It never uses
> `--force`/`-f`, `-B`, `branch -D`, `reset`, `checkout` or `clean`, never writes into an existing
> non-worktree directory, holds a per-path lock so one process creates a worktree at most once, and never
> deletes or edits `*.jsonl` transcripts or any file under `~/.claude`. No other git write is allowed."*

Also add one line to `CLAUDE.md` "App-owned state" pointing at this exception (L2d).

### B. Concurrency: N sessions of one repo at once

What happens when K worktree sessions of repo R are clicked at once:
1. **No lock** around `session_cwd` (tail) or `place` (file reads).
2. **Lookup (3133-3159).** A session-pty hit returns at once. Otherwise one handler reserves
   `_FOLDER_SPAWNING[root]` and spawns outside `_LOCK`. The others `pending.wait(≤3 s)`, which really
   lasts as long as the fork, because `reserved.set()` runs in `finally`.
3. **Claim (3212-3240).** **Any one** handler wins the claim under `_LOCK`. Every other handler sees `fg`
   set and immediately spawns its own overflow claude in **its own worktree top**: no shared wait and no
   bare run at the root.
4. **Cold or warming shell (S3, decided).** No resume/new opener claims a shell whose startup has not
   settled. If `fp is None`, or `not fp.startup_done`, or `_FOLDER_SPAWNING[root]` is reserved, the opener
   **does not wait** (no `pending.wait`). It spawns a dedicated claude pty at its worktree top right away
   (`overflow=True`, so it vanishes on exit). Only when the root shell is absent and unreserved does it
   also reserve and spawn the root folder shell **to warm** (no claim, a `_folder_settled` thread only),
   and only if two slots are free.
   **Slot accounting is atomic with the spawn decision (D6):** a module counter `_SLOTS_RESERVED`
   (guarded by `_LOCK`). In ONE `_LOCK` section the opener checks
   `_live_count() + _SLOTS_RESERVED + need <= MAX_TERMS` (need = 1 for the dedicated claude, +1 if it
   also warms) and increments `_SLOTS_RESERVED` by `need`. The forks run **outside** the lock, and a
   `finally` decrements once each pty is in `PTYS` or the spawn failed. An opener that can't reserve even 1
   gets the existing 429 with the slot list. The dedicated spawn therefore goes through the same 429 path,
   and K concurrent cold openers can never overshoot `MAX_TERMS`.
   **Warm-shell settle timeout (D6):** the warm thread is `_folder_settled(fp, now + FOLDER_STARTUP_WAIT)`
   (120 s). On `False` (never settled) it marks `startup_done = True` (existing `finally`). If the shell is
   still not at its prompt (`_fg_pgid(fp) != fp.pid`) **and** has no viewers, it closes it through the
   `close_pty` kill path, so a wedged warm shell never pins a slot or makes openers go dedicated forever.
   The `_FOLDER_SPAWNING` reservation is already released in `finally` right after the fork.
   **A session that already runs in a dedicated claude** is found first by `_session_pty`. Verified in
   code: `_session_ptys` (3512-3527) yields a non-folder pty with `mode == "resume" and p.session == sid`
   (or `spawned == sid`). So a later Resume of S returns S's dedicated tty and never types into the warm
   shell (test below).
   - K cold openers: K dedicated claudes start in about 1–2 s each, plus 1 warming shell, with nobody
     waiting.
   - Later opens find the settled warm shell idle and type into it (item 5).
   - `cwd`-mode opens still wait on and attach to the shell (they need it), as today.
5. Warm shell: the claimant's sync `_inject_argv` (about 0.3 s with S2; worst case 8 s + 8 s) runs outside
   `_LOCK` in its own handler. Nobody waits on it.
6. The same session clicked twice: `_session_pty`, or the `fg.session == sid` peek, gives the same tty.
7. Background sessions: `_swap_candidate`/`_swap_in` (0.5–8 s) block only that handler. A takeover may now
   displace an unwatched thin client from a *different* worktree of R. That is acceptable, goes in the PR
   notes, and the line it types is `cd`'d (row 13).
8. Fork/attach retry after `fg` is cleared types the `cd` line from `run_dirs` (row 1).
9. K beyond `MAX_TERMS` (12) gets the existing 429. External opens share no state.
9a. Recreate (§A2): the per-path lock serialises only clicks on the same removed worktree **within one
    server process**, covering both its external and in-app routes. It is never held with `term_vt._LOCK`,
    and other sessions of the repo are never blocked by it. **Across processes** (8787 plus 8790), git
    itself refuses the second `worktree add`, and the loser's one re-check sees a live worktree of `root`
    on the planned branch and treats that as success (D3). The worst case is one extra git error inside
    the loser, never two worktrees.
10. **Guarantee:** no claude for a worktree session is ever spawned or typed with cwd == R's root without
    `cd <worktree top>`.

PR notes (user-visible, no code):
- Resuming B into the idle shared root shell types into a tab A's user may be watching, which is the
  sharing the user asked for.
- The `sh -c …` line is echoed and lands in HISTFILE.
- On Claude exit the user is at the root.
- Bare-repo and `--separate-git-dir` layouts stay unmapped. This is stated, not claimed as "any".

### C. Async inventory (complete as far as read)

The server is a `ThreadingHTTPServer` (`server.py` 838), with one thread per request. No asyncio rewrite.

| # | file:line | What blocks | Cost | Can be async? | Scope |
|---|---|---|---|---|---|
| 1 | `term_gate.py` 71-95 `session_cwd` → `parse_any` (also `term_run.py` 470) | full parse for one field | **5.63 s** cold / 0.019 s warm (measured) | yes: tail read | **IN: S1** |
| 2 | `term_vt.py` 4530 via `_inject_argv` 1946 | quiet clock starts at call time | **≥1.5 s per warm reuse** | yes: seed from `last_output` (Screen branch) | **IN: S2** |
| 3 | `term_vt.py` 3602/3576 deferred folder start | rc files before claude is typed (already off the handler) | **11–13 s** (measured) | yes: exec claude in a dedicated pty while the shell warms (+1 slot) | **IN: S3 (E3 decided), L5** |
| 3a | new `term_gate.recreate_worktree` | `git worktree add` (checkout) inside the confirmed handler | ~0.1–2 s (reasoned, repo size) | not needed: a one-off, user-confirmed op, and the SPA shows "recreating…" | in scope (L2d), sync by design |
| 4 | `term_vt.py` 3404-3503 `_swap_candidate`/`_swap_in` | sleep 0.5 s, ps 3380, lsof 3397, detach waits 2–8 s in handler | 0.5–8 s (read) | partly: return the tty, swap on a thread | deferred |
| 5 | `term_vt.py` 3365 `_background_target` (also `term_launch.py` 191) | daemon roster plus transcript tail on every resume | 2 ms measured for one session; unmeasured under load | could run concurrently with placement; not needed | keep (row 12) |
| 6 | `term_vt.py` 3130 `resolve_spawned(throttle=0, new_only=True)` per resume, and throttled on every `GET /api/term/list` poll | `newest_session_in_cwd` globs and stats **every** transcript per candidate | **unmeasured, O(all transcripts)** | yes: index by cwd, or run off-request | deferred (relabelled, row 12) |
| 7 | `term_vt.py` 3166 `pending.wait(FOLDER_SPAWN_WAIT)` | second opener waits for the first's fork | ms, cap 3 s | not needed: bounded and tested | keep + test |
| 8 | `term_vt.py` 3826 `close_pty` CLOSE_CONFIRM_WAIT | waits for proof of death | ≤2 s | no: `closed` is that proof | keep |
| 9 | `term_launch.py` 212 osascript `timeout=10` | AppleScript round trip | ~0.3–2 s (reasoned) | yes, but loses Automation-denied errors | deferred (S4) |
| 10 | `server.py` 566 `/api/title` → `_sync_title_to_claude` → `term_vt.inject` | quiescence wait + resend | ≥1.5 s, up to ~9 s | yes: `synced:"pending"` plus a thread (contract change) | deferred |
| 11 | `term_vt.py` 4571 `inject()` | quiescence before typing into Claude | ≥1.5 s by design | no: Claude's footer makes `last_output` unusable | keep |
| 12 | `server.py` 450 `/api/search` → `search_all` | scans every session | **6.4–15.2 s/query** (measured) | yes: cached index / incremental, or streaming | deferred (largest non-terminal cost) |
| 13 | `web/app.js` 1365 `doSearch` | awaits #12 with no AbortController; a stale answer can overwrite a newer one | as #12 | yes: abort the previous fetch | deferred |
| 14 | `server.py` 405 `/api/list` → `all_sessions` | list build, polled every 5 s per client (`app.js` 1454) | 0.32 s (measured) | yes: short-TTL shared memo | deferred (S5) |
| 15 | `server.py` 498 `/api/session` → `parse_any` | first open of a big session | 5.6 s cold | yes: background pre-parse of live sessions | deferred |
| 16 | `server.py` 452-497 drill routes | provider drill | not measured | likely not needed | not examined |
| 17 | `providers/claude.py` 615 `_ps_lstart` | `ps`, timeout 2 | ~10 ms | no | keep |
| 18 | `term_vt.py` 4069 `_foreground_is_claude` `ps` | comm per pgid (cached 5 s) on the 2 s attached poll | ~10 ms on a miss | no | keep |
| 19 | `term_vt.py` 3930 `_claude_work_children` `ps -A` | process table (reaper/close/swap) | ~20–50 ms (reasoned) | no | keep |
| 20 | `term_vt.py` 3120 `gateway.or_launcher()` | fs check per open | ms | no | keep |
| 21 | `tunnel.py` 266/272 `proc.wait(timeout=3)` ×2; 181 start | cloudflared teardown in handler | ≤6 s | yes: respond, reap on a thread | deferred |
| 22 | `store.py` 451 listdir retry sleep | fork snapshot | ms | no | keep |
| 23 | git/gh subprocesses | **none** on this base. Placement adds none (file reads instead of a 58 ms `rev-parse`); only the user-confirmed recreate (3a) runs git | — | — | — |
| 24 | `web/ext_vt.js` 2911 `GET /api/term/list` before `POST /api/term/pty` | serial round trip | 1 RTT (~5 ms local / 100–300 ms tunnel) | yes: skip for resume | deferred (S6) |
| 25 | `web/ext_vt.js` 1817 `_loadXtermAssets` after the POST | ~480 KB on the first open | tunnel/phone | yes: start on the click (still lazy) | deferred (S6) |
| 26 | `web/ext_vt.js` 2954 `requestAnimationFrame` | cols/rows measure | ~16 ms | no | keep |
| 27 | `web/app.js` 1322/1664; `web/ext_cr_term.js` 1205-1226 | polls | — | already concurrent, with in-flight guards | — |
| 28 | `web/ext_launch.js` 37 `probe()` | one POST per page load | 1 RTT | no need | keep |

## Sequencing and legs (after sign-off only)

The order is **L0a → L1 → L2a → L2b → L2d → L5 → L2c → L3 ∥ → L4 → L0b**.
- L1 first: `_tail_scan` keys and `recorded_run_dir`.
- L2a's pure helpers come before L2b's wiring.
- L2d (recreate) needs L2b's `place` 409 shape.
- L5 (S3) changes open_pty's claim branch, so it lands after L2b/L2d and before L2c, whose concurrency
  assertions are written against the final S3 behaviour.
- L3 touches only `_wait_for_quiescence`'s signature plus one call, so it can run after L1 in parallel.
- L0 is split: (a) validates shell mechanics before code; (b) is a post-L5 server check.

**Model for every implementation leg:** sonnet. L0: sonnet (process inspection). Each L0 session is a real
`claude -p` call, so keep the brief to the listed runs.

**L0a, shell spike (scratch only, before L2b).** Scratch git repo in `$TMPDIR` with two `git worktree add`
dirs. Make one hand-typed line longer than 200 chars, with a quoted path containing `'`. Run each check in
a login **zsh** and in **`/bin/bash`** (plus fish if installed):
- (a) `sh -c 'cd "$0" && exec "$@"' <wt> <abs claude> --resume <id>` gives claude's cwd
  (`lsof -a -d cwd -p`) == wt; fg pgid comm == `claude` and `term_vt._foreground_is_claude(fd)` is True (C5); parent shell cwd == root.
- (b) `type claude` in the real login shell (alias or function present?).
- (c) The hazard: a bare resume of an unrecorded session from the root runs at the root.

Tear down: processes, the scratch repo, and the `~/.claude/projects/-private-var-…` dirs this leg created
(proof of ownership). Results go under "L0 result" here. *If (a) fails in any shell, use the fallback in
Risk 1.*

| Leg | Files / signatures | Tests (each named test RED when its fix is reverted; "guard" = regression guard, green today too) |
|---|---|---|
| **L1** S1 + tail | `providers/claude.py` `_tail_scan` (+`cwd`, `cwds`, `wt`, `wt_seen`, `gitBranch`); `term_gate.py` `session_cwd` fast path, `_existing_ancestor`, `recorded_run_dir(sid)` | `tests/test_term_home.py`: `TestTailScanCwd.test_latest_and_history` (cwds newest-first, null `wt` clears); `TestSessionCwdFastPath` (`parse_any` patched to `side_effect=AssertionError`, still returns the cwd); `test_tail_empty_falls_back` (a final 120 KB line; `parse_any` patched to count calls → used once); `test_no_transcript_falls_back`; `TestRunDirPreference.test_wt_preferred_over_later_root_cwd` (cwds W, W/sub, then root, no record → run top W), `test_worktree_state_wins`, `test_worktree_state_null_keeps_latest`. `tests/test_resume_missing_cwd.py` unchanged (guard). |
| **L2a** helpers | `util.py` `git_worktree_root -> (root, wt_top)`, `deleted_worktree_root`; `term_gate.py` `place`, `home_note` | Tables on fabricated layouts. RED: linked wt → (root, top); subdir → same top; **relative gitdir** → root; **symlinked tmp root** → realpath root; deleted + admin entry → root; deleted + marker → root. Guards: main checkout → ""; a main checkout's own subdir → ""; submodule → ""; bare → ""; plain deleted folder → "". `place` rows: `test_order_deleted_wt_ancestor_inside_repo` (ancestor `<root>/.claude/worktrees` → E1 branch, never row 4); Auggie and fake sid → `raw = cwd`. Real-git cross-check skipped without `git`. |
| **L2b** wiring | `term_vt.py`: `Pty.run_dirs`, `_run_dir`, `_inject_argv(…, sid=None)` (sh -c, no bracket, CR/LF refusal), claim 3229, `_swap_in(…, run_dir=None)` + caller 3346, `_folder_retype` 2411 keeps the entry, callers 3276/3615/2428/3487 pass `sid`, overflow 3306, open_pty placement replacing 3090-3091, `resolve_spawned` 2075/2109/2123, `record_fork` 2499/2556, `_term_title` 2149, `_live_list` 2203 (+`shell_cwd`); `term_launch.py` placement replacing 196-198, `build_script(…, run_dir=None)`; `registry.py` `parse_any` keys; `web/ext_vt.js` delete the 2925/3851 clauses | `TestOpenPtyAtRoot` (`test_folder_terminal.py` fixtures): resume/cwd/new → folder `cwd == root`; golden typed line `sh -c 'cd "$0" && exec "$@"' '<top>' claude --resume <sid>`; **`test_launcher_not_resolved_by_server_path`** (`shutil.which` patched to `/wrong/claude` → never in the line, C1); **`test_idle_root_shell_not_labelled_worktree`** (after a `new` claim ends, `_live_list` cwd == root, C3); **`test_parse_any_no_recursion_on_huge_last_line`** (a 120 KB last line → `/api/session` 200 and `parse_any` entered once, C2); overflow resume `cwd == top`; a second worktree session reuses the tty. **`test_fork_retry_after_fg_cleared_still_cds`** (claim with run_dir W, `pt.fg = None`, `_retry_with_fork` with prompt/quiescence stubbed, captured bytes contain `cd "$0"` and W; RED with claim-only storage). **`test_swap_in_types_cd_line`** (row 13). **`test_inject_argv_never_brackets_long_shell_line`** (line over 250 chars has no `\x1b[200~`) and a 199/201 golden pair. **`test_inject_argv_refuses_newline_path`**. **`test_resolve_spawned_forked_cwds_uses_run_dir`** (forked root folder with `run_dirs={S: W}` → `newest_session_in_cwd` never called for W). **`test_live_list_labels_worktree_not_root`** (`cwd == W`, `shell_cwd == root`, title basename W). `test_fg_public_has_no_run_dirs` (guard). **`test_deleted_worktree_all_modes_409_with_recreate`** through `open_pty` itself (cwd/new/resume answer 409 with `recreate.token` and the server message; RED today: 404). No spawn is recorded. `TestOpenTerminalAtRoot`: the script holds `cd '<root>' && sh -c` and the run dir; a run_dir with `'` and `"` round-trips through shlex.split after AppleScript unescape. `TestRegistryTermHome`: Claude and Auggie fixtures. Node DOM harness: `openVT(sid, "cwd")` with a matching folder row POSTs instead of peeking (RED with the clause present). Eval `tests/test_integration.py::TestServerEndToEnd`: `GET /api/session` keys; `POST /api/term/pty` on a deleted-wt fixture gives 409 with `recreate`. `make bundle` + `python dist/tracker.py --selfcheck`. |
| **L2d** recreate (E1) | `term_gate.py`: `recreate_plan(sid, raw, root, meta=None) -> dict | None`, `recreate_worktree(plan) -> (ok, path_or_err)` (lost-race re-check), `_valid_recreate_path(raw, root)`, `_admin_dir_for(root, path)` (by `gitdir` content), `_default_base(root)`, `_make_token`/`_check_token` (HMAC, `exp`, single-use `_USED_TOKENS`), `_RECREATE_LOCKS`, `_git(root, *args)` (env stripped, timeout 30, argv allowlist asserted); `registry.py` note text; `term_vt.open_pty` + `term_launch.open_terminal` token handling; `web/ext_vt.js` `ExtVT.confirmRecreate`, called from `_openVTFresh`, `mountInto`, `ext_launch.js` `openTerm`, `ext_cr_term.js` `_openExternal`, `ext_cr_boot.js` answerSession; `.claude/rules/conventions.md` rule 6 exception (drafted text in §A2), plus one line in `CLAUDE.md` | `tests/test_term_recreate.py`, run against a **real** tmp git repo (skipped without `git`), never the user's repos. **`test_plan_existing_branch_same_path`** (branch kept → `worktree add <path> B`). **`test_plan_branch_deleted_uses_reflog_tip`** (`rm -rf` the worktree so the admin entry survives, delete the branch → new `-cont-` branch at `G/logs/HEAD`'s sha, `base_kind == "last-commit"`). **`test_plan_normal_removal_uses_default_branch_not_checkout_head`** (D1: `git worktree remove w` + `branch -D f` (setup), then `checkout -b unrelated` + a commit in the main checkout → `base == main's sha`, never `unrelated`'s; `base_kind == "default-branch"`; the summary contains "only present if they were merged"; RED on v4). **`test_plan_no_default_branch_no_recreate`**. **`test_admin_dir_found_by_gitdir_not_basename`** (D2: two worktrees named `api` in different parents → admin dirs `api`/`api1`; `rm -rf` the second → the plan reads `api1`'s reflog; RED with basename lookup). **`test_plan_transcript_branch_is_primary`** (admin `G/HEAD` disagrees and the transcript has `gitBranch` → the transcript wins). **`test_plan_branch_checked_out_elsewhere_new_branch`**. **`test_recreate_then_resume_same_sid`** (after the confirmed POST, the dir exists as a worktree on the expected branch and the typed/spawned line resumes the **same** sid with `cd "$0"` = path). **`test_token_mismatch_replans_no_write`** (no new ref, no dir). **`test_token_expired_replans`** (`exp` in the past → 409 with a fresh plan, no write; RED on v4). **`test_token_single_use`** (the same token twice → the second re-plans). **`test_token_from_other_process_rejected`** (a different `_SECRET`). **`test_invalid_path_no_recreate_key`** (D4: recorded cwd `/tmp/x/y` with `/tmp/x` missing → 409 with no `recreate`; and a path equal to `$HOME` or root; RED on v4). **`test_recreate_readonly_or_tunnel_visitor_403`** (D4: a read-only/tunnel visitor POST with a valid token → 403, no `_git` call). **`test_lost_race_is_success`** (D3: `_git_add` patched to really create the worktree, as the other process would, and then return failure → `recreate_worktree` returns `(True, path)`; RED on v4). **`test_lost_race_wrong_branch_is_error`** (the path became a worktree on some other branch → error, no resume). **`test_reclone_same_path_uses_default_base`** (D7: re-init the repo at the same path → the stale sha fails `cat-file -e`, so the default base applies). **`test_path_occupied_refused_untouched`** (a plain dir with a file stays byte-identical). **`test_repo_gone_409_without_recreate`**. **`test_never_force`** (every `_git` argv recorded; none contains `-f`, `--force`, `-B`, `-D`, `reset`, `checkout`, `clean`). **`test_concurrent_confirms_one_worktree`** (Barrier(4) confirmed POSTs for one session, plus 2 sessions sharing the path → exactly one `worktree add` call; all four get a tty; RED with the lock removed). **`test_registered_missing_prunes_then_adds`** (also asserts that the summary counts the cleared sibling registrations, D2). **`test_no_git_on_poll`** (`GET /api/session` on a deleted-wt fixture records zero `_git` calls; RED if the plan ever runs git at note time). Node DOM harness (D5): a 409 with `recreate` shows `confirm` with the server text and the retry carries the token, for **all 5 call sites**; a declined confirm sends nothing. **`test_confirm_retry_dropped_when_superseded`** (the stubbed `confirm` returns true after bumping `openGen` → no second fetch; RED without the guard). **`test_suppressed_confirm_falls_back_to_toast`** (`confirm` returns false in < 50 ms → the toast shows the server text). **`test_extvt_resolved_lazily`** (each of `ext_launch.js`/`ext_cr_term.js`/`ext_cr_boot.js` references `window.ExtVT.confirmRecreate` inside the handler, not at module scope; the assembled-bundle run proves the call resolves). |
| **L5** S3 cold-open | `term_vt.open_pty` claim branch (3212-3317): a resume/new opener with `fp is None`, `not fp.startup_done` or a reserved `_FOLDER_SPAWNING[root]` skips the claim and `pending.wait` and spawns a dedicated claude at `run_dir or cwd`; slots are reserved atomically under `_LOCK` via `_SLOTS_RESERVED` (forks outside, `finally` releases); if the root shell is absent and unreserved and two slots reserve, it also spawns the root folder shell with only the `_folder_settled` thread (no claim, no `_deferred_folder_start`), plus the settle-timeout close of a wedged warm shell. `_deferred_folder_start` stays for nothing else to call (deleted only if grep shows no caller; else left) | `tests/test_term_s3.py`. **`test_cold_resume_execs_claude_now_and_warms_root`** (no folder pty → 2 spawns: claude argv at the worktree top, `overflow=True`; login shell at the root, `folder=True`, `fg is None`; the response tty is the claude one; no thread named `folder-start-*`; RED on revert, which today does one shell spawn plus a deferred type). **`test_resume_during_warm_goes_dedicated_without_wait`** (fp with `startup_done=False` → dedicated, and `threading.Event.wait` is never called on the reservation; RED on revert). **`test_resume_while_reserved_does_not_wait`**. **`test_warm_skipped_at_cap`** (`_live_count() == MAX_TERMS-1` → only the dedicated spawn). **`test_cold_burst_never_overshoots_cap`** (D6: 11 live, 3 concurrent cold openers with the fake spawn sleeping 0.5 s → at most 12 live, the rest 429; RED with a non-atomic count). **`test_resume_of_session_in_dedicated_returns_same_tty`** (D6: open S cold (dedicated), settle the warm shell, open S again → the same tty, zero typed lines in the root shell). **`test_wedged_warm_shell_is_closed_after_settle_timeout`** (D6: `_folder_settled` patched to return False, shell fg ≠ pid, 0 viewers → closed and the slot freed; RED without the timeout handling). **`test_settled_warm_shell_is_reused`** (after `startup_done`, the next resume types the `sh -c` line into it, `reused: True`). Guard: `test_cwd_mode_cold_still_opens_shell`. |
| **L2c** concurrency | `tests/test_term_root_concurrency.py` (plus any fix it forces) | Fixture: tmp repo, K=4 fabricated worktrees, transcripts in a tmp `config.PROJECTS`. Stubs: `spawn` with a fake that sleeps 0.5 s (C4), records `(cwd, argv)` and returns a fake Pty; `_fg_pgid` idle; `_wait_for_quiescence` True; `_inject_write` captured; **`_start_backstop`, `_folder_settled`, `_background_target` stubbed**. `term_vt._LOCK` is swapped for an instrumented lock recording the max hold time. **`test_k_simultaneous_resumes_warm`** (settled idle root shell, Barrier(K)): exactly 1 typed line and K−1 dedicated spawns, each `cwd == its top`. **`test_k_simultaneous_resumes_cold`** (no shell, S3): K dedicated claude spawns at their tops, at most 1 warming root shell, 0 typed lines, and no `Event.wait` on the reservation by any resume opener. In both, every recorded spawn/line has claude `cwd ≠ root` or contains `cd "$0"` (RED when the sh -c wrapper, the dedicated run dir, or S3's no-wait branch is reverted). Max lock hold < 0.2 s (C4), and each handler finishes < 2.0 s (generous). RED proof: temporarily move `spawn` under `_LOCK` and watch the hold-time assert fail. `test_k_simultaneous_open_terminal_share_root` (all root). Guards: `test_waiter_bounded_by_spawn`, `test_same_session_twice_one_tty`. Claimant identity is never asserted. |
| **L3** S2 | `term_vt.py` `_wait_for_quiescence(pt, quiet_since=None)`: Screen branch `last_change = min(start, quiet_since)` when given; `_inject_argv` passes `quiet_since=pt.last_output`; `inject()` 4648 unchanged | **`TestQuietSeed`** with a pty holding a **real `Screen`**, `INJECT_QUIET_WINDOW=0.4`, **`INJECT_MIN_WAIT=0.05`**: seeded now−10 → < 0.2 s (RED on revert); unseeded → ≥ 0.4 s; seeded now → ≥ 0.4 s. `test_inject_argv_seeds_from_last_output` (kwarg asserted). |
| **L4** SPA note | `web/ext_cr_term.js` (markup 133 `data-el="homenote"`, el map 252, `_loadHeaderInfo` 1093); `web/ext_cr_term.css` one muted rule; `web/ext_launch.js` `render(d)` 391 escaped span | Node DOM harness (`tests/test_working_glow_board.py` helpers): the note renders in both UIs and is hidden when empty; a full-bundle load check (the gate misses load-time JS/CSS errors). |

**L0b (post-L5, test server on a spare port; `unset TRACKER_AUTH`; never `pkill -f aitracker`).**
1. Cold: two threads `POST /api/term/pty` resume two scratch worktree sessions at once. Expect two
   dedicated claudes at once, plus one warming root shell. `lsof` shows both claudes in their worktrees and
   neither at the root.
2. After the shell settles, a third resume types into it, and `/api/term/attached` is true.
3. Remove one scratch worktree (`git worktree remove`, scratch repo only). Resume gives 409 with
   `recreate`. A POST with the token recreates it, and the same sid resumes there. Two confirmed POSTs at
   once create it once.

Tear down as in L0a.

**Gate traps:**
- `unset TRACKER_AUTH;` before every test and `git commit` (the hook runs the full gate in 180–380 s, so
  the timeout must be over 2 min).
- One test module per process (OOM).
- `test_term_vt` has a known flaky backstop.
- Restart the test server after any UI or parse change.

**Review and ship (after sign-off):**
1. Opus adversarial review of the implementation. Its brief includes a `grep -n "\.cwd\b" term_vt.py`
   audit and the re-run of the L2c tests under load (2–3 module processes in parallel).
2. Reconcile.
3. `/tracker-gap` route.
4. `/branch-sync`, the gate green again, push the branch to `personal`, then `/tracker-push`.

## Risky spots and fallbacks
1. **`sh -c` and job control in some shell** (L0a). *Fallback:* the `( cd … && exec … )` form for zsh/bash
   only, and a dedicated overflow pty (no sharing) for fish.
2. **A `pt.cwd` consumer meaning "where claude runs" is missed.** The audited list is row 4 above. The L2c
   invariant check covers every spawn and typed line.
3. **Launcher resolution.** `argv[0]` is passed unchanged (review C1), so the login shell's PATH decides,
   as today. Test: a patched `shutil.which` returning `/wrong/claude` never appears in the typed line.
4. **Recreate writes to the user's repo** (L2d).
   - Mitigations:
     - a one-click confirm with a server-built summary (honest `default-branch` wording);
     - an HMAC, single-use, 10-min token;
     - `_valid_recreate_path` (no path outside the repo, no parent creation);
     - an exact git argv allowlist with `test_never_force`;
     - a per-path lock plus the cross-process lost-race re-check;
     - a refusal on an occupied path;
     - a rule-6 exception;
     - tests only on tmp repos.
   - *Fallback if git misbehaves* (an older git without `worktree add -b <b> <path> <base>` ordering, or
     odd prune semantics): ship the 409 message only, plus a copyable recreate command, with no write.
5. **`git worktree prune` is repo-wide by git's design** (D2).
   - It drops only registrations whose dirs are already gone; no file is touched.
   - Sibling hand-deleted worktrees lose their admin reflog, so their later recreate falls back to the
     default-branch base and says so.
   - Mitigations: prune only when the target path is still registered-but-missing (located by `gitdir`
     content), read this path's `G/logs/HEAD` first, and count the cleared registrations in the confirm
     summary.
   - **Accepted and PR-noted.** The snapshot-to-`worktree_heads.json` alternative was rejected as
     overbuilt.
5a. **The base for a deleted branch is usually the default-branch tip, not the session's last commit**
    (D1). `git worktree remove` plus `branch -d` leaves nothing to recover it from. The summary says so in
    plain words, and the primary checkout's own HEAD is never used.
6. **S3 doubles the slot use on a cold open** (claude plus a warming shell). Reservation is atomic with
   the spawn decision (`_SLOTS_RESERVED`, D6), and the warm is skipped when two slots aren't free. Note: the first cold resume now never uses the shared shell (later ones
   do), which is the trade the user chose.
7. **Cross-worktree takeover** (§B.7): PR note plus `test_swap_in_types_cd_line`.
8. **Concurrent agents in this worktree** are editing `tests/`/`aitracker/` for the base gate. Every leg
   re-reads the cited lines first, and no leg touches their files outside its listed set.

## Decisions (all decided 2026-11-16; none open)
- **E1:** recreate on one-click confirm (§A2).
- **E2:** subshell for every session.
- **E3:** include S3 (L5).
- Remaining judgment calls are made in this plan and are open to overrule at sign-off:
  - the `-cont-<sid8>` branch naming;
  - reflog tip, else main HEAD, as the base for a deleted branch;
  - confirm rather than automatic recreate;
  - the prune-when-registered rule.

## Not examined
- `_resume_backstop` and `_retry_with_attach` internals beyond their retype/claim lines. The `_swap_in`
  release/restore logic beyond the claim site.
- `registry.parse_any` caching, and whether `home_note`'s stats run on cached responses.
- The Auggie `meta.cwd` shape (not opened). The Auggie terminal path end to end, including recreate for
  an Auggie session (the same util code; no Auggie fixture yet).
- Drill-route cost (#16). `tunnel.start` wait behaviour. The Control Room search path versus `doSearch`.
- Nested worktrees, and a worktree whose main checkout is missing.
- A real GUI run of external Terminal/iTerm, including the confirm dialog on the board's external Resume.
- The phone/tablet layout of `term_home_note`, and native `confirm()` inside an installed PWA.
- Git behaviour of `worktree add` on a path registered-but-missing without a prune. I read git docs from
  memory only; L0b and `test_registered_missing_prunes_then_adds` verify it.
- The `ext_cr_boot.js` answerSession body (only its route and its fallback are known from
  `tests/test_cr_board_resume_button.py`).
- Whether `_deferred_folder_start` has callers left after L5 (grep at implementation).

---

## Reconciliation of plan v2 vs reviews A (opus) and B (sonnet) — main thread, 2026-11-15

Inputs side by side: plan v2 (this file, above) · `reports/terminal-at-root-review-A.md` (opus: 1 blocker, 4 major, 7 minor) ·
`reports/terminal-at-root-review-B.md` (sonnet: 0 blocker, 4 major, 8 minor). Each review ends with its own clean plan.

Spot-checked against the code by the main thread:
- `term_vt.py:1880` `_refresh_fg` sets `pt.fg = None` when the shell regains the foreground -> a `run_dir` stored in the claim is lost.
- `term_vt.py:4404` `INJECT_BRACKET_LEN_THRESHOLD = 200`; `_bracket_if_needed` (4561) wraps long injected lines in bracketed paste.
- `term_vt.py:3088-3091` cwd/new modes call `session_cwd(sid)` without `resume=True` and 404 before any placement.
- `term_gate.py:71-95` resume walk on a deleted worktree lands on `<root>/.claude/worktrees` (inside the primary checkout's tree).

| # | Finding | Source | Verdict | Fix taken |
|---|---|---|---|---|
| 1 | Fork/attach retry loses `run_dir` (claim cleared by `_refresh_fg`, rebuilt by `_folder_retype`) -> bare `claude` typed at the root = primary checkout | A F1 (blocker) + B B1 (major) | **Confirmed** (1880), both reviewers independently | Store `run_dir` on the Pty per session (`Pty.run_dirs {sid: dir}`, never cleared by `_refresh_fg`); `_inject_argv` / `_folder_retype` / `_swap_in` read it by sid. Test: refused resume -> fork retry line contains `cd <wt>`; red with dict reverted to claim storage. |
| 2 | Long subshell line bracket-pasted -> mangled on bash 3.2 | A F2 | **Confirmed** (4404/4561) | Never bracket in `_inject_argv`; refuse any argv line containing CR/LF. Not a global change to `inject()`. |
| 3 | `exec claude` / `(…)` skips aliases, breaks under fish | A F3, B minor | **Confirmed in reasoning, not run** | Resolve launcher to an absolute path server-side (already have `_launcher_for`) and use the shell-agnostic `sh -c 'cd "$0" && exec "$@"' <wt> <argv…>` form (B). Covers zsh/bash/fish in one shape. L0 spike must run it in zsh and bash. |
| 4 | Missed root-vs-worktree call sites: `forked_cwds` (2075), terminal-list labels/cwd (2149/2203), `record_fork` first-vs-latest cwd; SPA `t.cwd === targetCwd` shortcut | A F4, B minor | **Confirmed by both** | Add to L2 call-site list; list/labels report the session's run dir, not the shell's cwd. |
| 5 | Latest cwd may be a subdir of the worktree or the root itself; tail read may find no cwd | A F5, B minor | **Confirmed** | Run dir = top of the latest worktree the session used (latest `worktree-state`, else latest cwd mapped to its worktree top); full-parse fallback when the tail has no cwd. |
| 6 | cwd/new modes 404 before `place()` on deleted worktree -> plan's rows unreachable | B B2 | **Confirmed** (3090) | Compute recorded cwd + placement before the 404, for all three modes and both launch paths. |
| 7 | 409 on deleted worktree blocks resumes that work today; "ancestor isn't the primary checkout" | B B3 | **Overstated** — the ancestor is `<root>/.claude/worktrees`, inside the primary repo, so git ops there hit the primary checkout. The usability cost is real | **User decision E1** (below). |
| 8 | S2 quiet-timer test can't go red (no real `Screen`, `INJECT_MIN_WAIT` unpatched) | A minor + B B4 | **Confirmed by both** | Test builds a Pty with a real `Screen`, patches `INJECT_MIN_WAIT`, asserts elapsed < bound; prove red by reverting. |
| 9 | One concurrency test can't go red; wall-clock asserts flaky; any of K may win the claim | A minor, B minor | **Confirmed** | Assert counts (1 shared root + K-1 dedicated, none bare at root) and a generous per-handler bound with a fake slow spawn, not real timing; prove red by holding the lock across spawn. |
| 10 | Relative `gitdir:` in worktree `.git` file (same bug in `util._git_branch`) ; symlinked paths | A minor, B minor | **Confirmed** | Resolve gitdir relative to the `.git` file's dir, `realpath` both sides. Fix only the new helper; `_git_branch` left alone (separate bug, note in PR). |
| 11 | `run_dir` leaking via `_fg_public`; `build_script` quoting | B minor, A minor | **Confirmed (minor)** | Don't expose run_dirs in `_fg_public` beyond a `run_dir` label; `shlex.quote` every path in `build_script`. |
| 12 | Deleted-worktree check order; `_background_target` and inventory row #18 O(all transcripts) | A minor, B minor | **Confirmed (minor)** | Order: resolve worktree -> existence check -> placement. Inventory rows updated, still deferred. |
| 13 | New cross-worktree takeover of an unwatched pane | plan v2 itself | **Missed by both reviews** (neither attacked it) | Keep as PR note; add to L2 test that a takeover never re-types a bare argv at the root (covered by #1's dict). |

Not examined by either review: interactive (non `-p`) resume re-entry in real claude (left to L0 spike), Auggie terminal path end-to-end, phone/tablet viewport of the new `term_home_note`.

### Decisions for the user (only these)
- **E1 deleted worktree:** (a, recommended) refuse Resume/New with the `git worktree add` recreate command; Open terminal opens the root shell with a note. (b) resume from the nearest existing ancestor as today (works after routine cleanup, but runs inside the primary repo tree).
- **E2 subshell for every worktree session** (recommended) vs plain resume from root for sessions Claude recorded.
- **E3 S3 (start claude immediately while the root shell warms, ~11 s off a cold first open, costs a second terminal slot):** recommended defer.

## Reconciliation of plan v3 vs review C (opus) — main thread, 2026-11-15

Review C verdict: READY WITH NITS (`reports/terminal-at-root-review-C.md`). Plan of record = **v3.1 = v3 + the fixes below**; no re-plan.

| # | Finding | Verdict | Fix taken |
|---|---|---|---|
| C1 | `shutil.which` under the server PATH can pick a different `claude` than the login shell's (today argv[0] is bare `claude`, `gateway.py:42`) | **Confirmed** | Keep `argv[0]` exactly as `gateway.launcher` returns it; drop `shutil.which`. Test: patched `which` -> `/wrong/claude` never appears in the typed line. |
| C2 | `parse_any -> place -> recorded_run_dir -> parse_any` recursion when the tail read finds no cwd (last line > 96 KB) -> 500 on every detail poll | **Confirmed in reasoning** (design-level; code not written yet) | `place/recorded_run_dir/home_note` take optional `meta=`; `parse_any` passes its own, the fallback never re-enters. Test: fixture with a 120 KB last line. |
| C3 | `_run_dir` falls through to never-cleared `run_dirs[""]` from a `new` -> idle root shell mislabelled as a worktree | **Confirmed** | No sid and no claim -> `p.cwd`. Test included. |
| C4 | 50 ms lock-hold bound flakes under parallel gate load | **Confirmed** (memory: load-sensitive term_vt backstop) | Fake spawn sleeps 0.5 s; assert hold < 0.2 s. |
| C5 | `sh -c … exec` keeps foreground detection working | **Confirmed nit** | L0a asserts `_foreground_is_claude` True. |

Status: plan **ready for user sign-off**. Open decisions E1–E3 unchanged (above). No source code written (user: "Stop at the plan").

## Reconciliation of plan v4 vs review D (opus) — main-thread verdicts, 2026-11-16

| # | Finding | Verdict | Fix taken (where in v4.1) |
|---|---|---|---|
| D1 | `git worktree remove` deletes the admin entry, so the reflog base is missing on the normal removal path and the plan falls back to the checkout's arbitrary HEAD | **Confirmed** (blocker) | The transcript `gitBranch` is the primary branch source. The base for a deleted branch is the surviving admin reflog, else the `_default_base` tip, never the checkout HEAD. The confirm summary for `default-branch` says the commits exist only if merged (§A2 rules 3, 6, summary table; `test_plan_normal_removal_uses_default_branch_not_checkout_head`). |
| D2 | Admin entry looked up by basename; repo-wide prune wipes sibling reflogs | **Confirmed** | `_admin_dir_for` matches by `gitdir` content. Prune runs only when the target path is still registered; the summary counts the cleared registrations; the loss is PR-noted, with no snapshot (§A2 Execution, Risk 5; `test_admin_dir_found_by_gitdir_not_basename`). |
| D3 | The per-path lock is in-process; a second server or route races into a raw git error | **Confirmed** | After a failed `add`, one re-check: a live worktree of `root` on the planned branch counts as success. No cross-process lock (§A2, §B 9a; `test_lost_race_is_success`, `test_lost_race_wrong_branch_is_error`). |
| D4 | Rule-6 exception gaps: path binding, parent creation, allowlist, token replay, read-only/tunnel gate | **Confirmed** | The exception text is tightened with all five points; `_valid_recreate_path`; the token is an HMAC (stdlib, about 8 lines) with a 10-min expiry, single-use (§A2 Token, rule-6 blockquote; `test_invalid_path_no_recreate_key`, `test_token_expired_replans`, `test_token_single_use`, `test_recreate_readonly_or_tunnel_visitor_403`). |
| D5 | Confirm wiring: supersede guard, suppressed confirm, `window.ExtVT` load order | **Confirmed** | `confirmRecreate(body, retry, stillCurrent)` with an `openGen` guard at the in-app sites; the toast fallback when confirm returns false in under 50 ms; `window.ExtVT` resolved lazily (§A2 Confirm wiring table; three Node tests). |
| D6 | S3: non-atomic slot check, the dedicated-session reuse case, a never-settled warm shell | **Confirmed** | `_SLOTS_RESERVED` reserved under `_LOCK` with the forks outside; `_session_ptys` (3512-3527) verified to index dedicated resume ptys; the settle timeout closes a wedged unwatched warm shell (§B 4, L5; three tests). |
| D7 | A re-cloned repo at the same path | **Accepted** (minor) | Every SHA is verified with `cat-file -e` against the current repo, so the default base applies; test only (`test_reclone_same_path_uses_default_base`). |
| C1 | Typed-line builder should restate "no `shutil.which`" | **Accepted** (nit) | Restated in §A at the `_inject_argv` builder, covering all four launch shapes. |

Status: v4.1 folds every D finding. No source or test file was touched (tests/ has a commit in flight).
Implementation still waits for user sign-off.

## Reconciliation of plan v4.1 vs review E (opus) — main thread, 2026-11-16

Review E verdict: READY WITH NITS (`reports/terminal-at-root-review-E.md`). Verified facts: transcripts record `gitBranch` on every line and it follows cwd; after a plain `rm -rf` of a worktree dir, `.git/worktrees/<n>/{gitdir,HEAD,logs/HEAD}` survive (git 2.54). Plan of record = **v4.2 = v4.1 + the fixes below**; no re-plan.

| # | Finding | Verdict | Fix taken |
|---|---|---|---|
| E0 | `_tail_scan` doesn't return `gitBranch` (only full meta pass, `claude.py:1830`) | **Confirmed** (reviewer-checked) | L1 adds `gitBranch` to the tail scan; test: tail-only fixture yields the branch. |
| E1 | After `rm -rf`, git still lists the dead entry as using branch B -> rules 4/5 wrongly create `B-cont-…` | **Confirmed** (scratch-repo verified) | Ignore the target path's own entry and any `prunable` entry when checking "B checked out elsewhere". Test: rm -rf'd worktree recreates on B, not `B-cont-`. |
| E2 | Toast fallback (confirm suppressed, iOS PWA) has no way to proceed | **Confirmed** | Toast carries a "Recreate" action button calling the same retry. Test: page asserts the toast action exists and is wired. |
| E3 | Pre-add accepts any branch, post-fail race check only the planned one | **Confirmed** | One rule: a live worktree at the path on any branch = success, report actual branch. Replace `test_lost_race_wrong_branch_is_error`. |
| E4 | 120 s warm-shell timeout sets `startup_done` before deciding to kill -> opener can claim the wedged shell | **Confirmed** | Decide `closing` atomically under `_LOCK` before releasing. Test: opener racing the timeout never gets the closing shell. |
| E5 | `gitBranch:"HEAD"` (detached) | **Confirmed nit** | Treat as no branch -> fallback rule. |

Not a defect (reviewer-checked): per-process HMAC secret (restart / other server just re-plans); the <50 ms confirm-suppressed heuristic.

Status: **plan v4.2 ready for user sign-off.** E1–E3 decided by the user (2026-11-16). No feature code written.
