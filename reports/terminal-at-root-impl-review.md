# terminal-at-root — adversarial implementation review (8cdad72..11b6f4d)

Reviewer stance: the implementers' reports were assumed to be false. I read code by grep and `sed -n` ranges only. I ran no tests.

## Attacks that did not find a defect

- **(1) claude at the repo root.** No path I traced runs it there.
  - Every typed path goes through `_inject_argv`: the first open, the fork/attach retry (term_vt.py:2480) and swap/takeover (:3594). It wraps the line in `sh -c 'cd "$0" && exec "$@"' <rd>` whenever `_run_dir(pt,sid)` differs from the shell cwd (term_vt.py:~1990).
  - `run_dirs[sid]` is set at the claim (:3320) and in `_swap_in` (:3565), and is never cleared.
  - Dedicated, overflow and cold opens spawn at `run_dir or cwd`. `place()` always gives `run = top` for a worktree when the mode is not "cwd".
  - The warm root shell (`_warm_root`) never has anything typed into it.
  - The external terminal (term_launch.py:117-146) wraps the whole resume || attach || fork chain in the subshell. Mode "cwd" there is correctly placed at the root.
- **(2) Per-path RLock.** It is taken only when `kind == "deleted"` and a token is present (term_gate.py:190). Ordinary opens never touch it, so there is no regression from serialising openers.
- **(2) Tokens.** The HMAC covers sid, path, branch, new_branch, base and expiry. Each token is single use (`_USED_TOKENS`, with expired entries pruned). The server re-plans before checking a token, so a stale plan fails closed with a fresh 409.
- **(2) Git commands.** The allowlist asserts its argv shapes. No command can take `-f`, `-B`, reset or checkout.
- **(3) Slot leaks.** `_spawn_dedicated` releases its slot in `finally`. `_warm_root` releases its slot and its `_FOLDER_SPAWNING` entry in `finally`. Nothing runs between `_slots_add` and `break`. I found no leak on exception paths.
- **(3) Wedged warm shell.** Closing it is atomic under `_LOCK`, together with `startup_done`.
- **(6) bundle.py.** Both rewrites assert that they matched, so drift upstream fails loudly.
- **(7) JS escaping.**
  - `confirmRecreate` uses `textContent`. It is gated by `openGen` / `!destroyed`.
  - The ext_launch note goes through `esc()`. ext_cr_term uses `textContent`.

## Findings

### F1 — major — the optional warm-up takes a slot that a real resume then cannot get

- **Defect:** term_vt.py:3213-3221 (cold branch). With exactly 2 free slots, opener A reserves 2: its dedicated pty plus the warm root shell. A simultaneous real resume B then computes `free = 0` and gets a 429. After that, the warm shell keeps holding the slot as a live idle pty. So the third and later real opens near `MAX_TERMS` are refused because of an optional cache.
- **Repro:**
  - Setup: `config.MAX_TERMS = 2`, 0 live ptys, two worktree sessions of the same repo (or of two repos).
  - Action: open both concurrently.
  - Actual: A gets 200 plus a warm shell, and B gets 429.
  - Expected: both get 200 and no warm shell.
  - The same happens sequentially: after A, `_live_count() == 2`, so B gets 429.
- **Direction:** the warm-up must never displace a real opener.
  - Warm only when a slot would still be left over for the next real opener: `free >= 3`.
  - Also, when a real opener is short exactly one slot, close or reuse an idle, unclaimed, viewer-less root shell rather than returning 429.
  - The guarantee that a cold burst never exceeds `MAX_TERMS` must not change.
- **Way:**
  - Change `free >= 2` to `free >= 3` (minimum fix).
  - Optionally, in both 429 branches (cold :3216 and overflow :3370), before refusing, pick a folder pty with `fp.folder and fp.fg is None and fp.viewers <= 0 and not fp.grants`. Mark it `closing` under `_LOCK` and treat its slot as free.
- **Test:** in tests/test_term_s3.py, `MAX_TERMS=2`, two cold resumes in sequence (mock spawn). Assert both return 200 and the spawn argv list has no `shell_argv`. This is red today: the second open gets 429.

### F2 — minor — the cold path roughly doubles the pty count for ordinary (non-worktree) folders

- **Defect:** term_vt.py:3213. Before this change, the first resume in a fresh folder was typed into that folder's single shell (`_deferred_folder_start`), so it used 1 pty. Now it uses a dedicated claude plus a warm shell, so 2 ptys. That holds for every plain folder, not only worktrees.
- **Repro:** resume 5 sessions in 5 plain folders with `MAX_TERMS=8`. Actual: the 5th open gets 429 (or no warm shell). Expected under the old contract: 5 ptys.
- **Direction:** this is the S3 design the user accepted (S3 included), so the behaviour stays. Combined with F1 it is what makes "many sessions" bite.
- **Way:** no change beyond F1 — document in notes and the PR. State that a cold open costs 2 slots when 3 or more are free, and 1 otherwise.
- **Test:** covered by the F1 test.

### F3 — minor — the tail memo returns a shallow copy

- **Defect:** providers/claude.py:112, `return dict(hit)`. The nested `cwds` list and `wt` dict are shared with the cached entry, so any caller that mutates them poisons later reads. None does today.
- **Repro:** `t = _tail_scan(p); t["cwds"].append("/x"); _tail_scan(p)["cwds"]`. Actual: it contains "/x". Expected: it does not.
- **Direction:** return an independent copy; keep the cache key unchanged.
- **Way:** `copy.deepcopy(hit)`, or store and return tuples (`cwds` as a tuple, `wt` as `dict(wt)`).
- **Test:** add the repro above to tests/test_term_home_helpers.py. It is red today.

### F4 — minor — the memo keeps dead keys per file

- **Defect:** providers/claude.py:89-110. Every append to a live transcript creates a new key `(path, mtime, size)`, and the old key for that path is never dropped. Eviction is FIFO at 256 entries. Memory stays bounded, but with many live sessions the cache churns and hits drop to near zero, so every poll re-reads 96 KB per session.
- **Stale result:** a truncate or rewrite with the same size and the same `mtime_ns` is practically impossible on append-only jsonl. No change for that — document in notes.
- **Direction:** keep at most one entry per realpath.
- **Way:** key the dict by realpath and store `(mtime_ns, size, nbytes, result)`. On a mismatch, replace the entry.
- **Test:** append to a temp transcript 300 times, calling `_tail_scan` after each append. Assert `len(_TAIL_MEMO) == 1`. It is red today.

### F5 — nit — the conventions rule-6 text lists fewer git commands than the code allows

- **Defect:** the exception text lists `rev-parse --verify --quiet refs/heads/<b>`. `_git_allowed` (term_gate.py:252) accepts any `refs/...`, and `_default_base` uses `refs/remotes/*/main`. It also passes 40-hex shas (they go to `cat-file`, not `rev-parse`).
  - `git worktree prune` prunes every stale registration in the repo, not only the target's. The UI does disclose this ("Also clears N…").
- **Direction:** make the documentation match the code. The code is safe because every allowed command is read-only.
- **Way:** amend the rule-6 text to `rev-parse --verify --quiet refs/(heads|remotes)/…`, and say that prune is repo-wide.
- **Test:** none (documentation only).

### F6 — nit — the per-path lock does not cover two server processes

- **Defect:** with two servers (8787 and 8790) and both confirms sent, both can reach `git worktree add`. The loser fails, then `live()` returns true, so it reports success.
- **Direction:** no change — git's own lock makes this safe. Document in notes.

### F7 — minor — deleted tests and invariants that are gone for good

These are tests/test_folder_terminal.py and tests/test_term_vt.py in f3ea647.

- **What was removed:**
  - `test_slow_shell_startup_queues_the_resume…`, `test_rc_job_longer…`, `test_job_after_settle_retries…` and `test_startup_wait_expiry_feeds_a_note…` are deleted.
  - "Exactly one pty per cold open" is now rewritten to expect 2.
  - These are consistent with S3 (cold opens go dedicated).
- **Invariant lost without a replacement:** "a shell that never reached its prompt never has claude typed into it." The new code never types into an unsettled shell, which makes the invariant structurally true. But nothing asserts that the settled-shell path still waits for the prompt.
- **`confirm(` allowance:** test_term_vt_client.py allows exactly one confirm call, at exact text. It is tight and fine.
- **Direction:** add one guard test.
- **Way:** in test_folder_terminal.py, make the fixture fp `startup_done=True` with `_fg_pgid != pid` (a job in the foreground). Assert the open goes dedicated and nothing is typed.
- **Test:** that test itself; it should be red if the `_fg_pgid(fp) == fp.pid` check at :3306 is removed.

## Verdict

**SHIP AFTER FIXES.** F1 is required: it directly contradicts the requirement that many sessions at once must not be held up. F3 and F4 are cheap and should be done. F2, F5 and F6 go in the notes. F7 adds one test.

## Not examined

- The full ~400-line tests/test_open_pty_at_root.py and tests/test_term_recreate.py bodies. I did not prove that they go red on revert. Rule-of-thumb only.
- Phone and tablet layout of the recreate toast and the CSS (ext_cr_term.css, ext_launch.css).
- `_admin_dir_for`, `_lenient_real` and `_admin_entries` internals (symlinked worktree paths).
- ext_cr_boot.js changes and the Control Room board's recreate wiring.
- The fork-session and attach backstop timing under the dedicated cold path (`_start_backstop` is called after the slot release; ordering not stress-tested).
- `registry.parse_any`'s per-poll term_home cost across many sessions (the listdir of `.git/worktrees` on every poll).
- The live test server; no tests were run.
