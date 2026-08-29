# Resume terminal stuck on the background-session refusal — fix log

Opened 2026-08-30. Worktree: `.claude/worktrees/resume-terminal-fix`, branch
`worktree-resume-terminal-fix`, based on local HEAD `62178a1`.

## The contract (user's words, verbatim)

> the resume terminal is always stuck in this screen always. and never really resumed, check the
> old or existing pattern and try to replicate that, resue the same pattern. The pattern was there
> before we started implementing the control room UI (new UI). that has introduced this regression
> also I would like to have the earlier solved pattern in place and add evals/tests for this
> scenario, such that we dont regress again with this /tracker-gap /tracker-push

Follow-up answers:
- On the fix direction: *"in the screenshot 'claude attach <first-8-id>' worked seamlessly, can we
  use that instead, I checked in my local terminal it worked smooth like butter."*
- On server restart: test server only; do not restart the live dashboard.
- Standing: name the model on every agent; fan out to cheap models.

### Clause-by-clause verdict

| # | Clause | Verdict |
|---|--------|---------|
| C1 | Resume terminal must stop hanging on the refusal | not-discharged |
| C2 | Replicate the earlier solved pattern / reuse the same seam | not-discharged |
| C3 | Use `claude attach <short>` rather than a fork copy | not-discharged |
| C4 | Add evals/tests so this cannot regress silently | not-discharged |
| C5 | `make check` green (`env -u TRACKER_AUTH make check`) | not-discharged |
| C6 | `/tracker-push` — push to `personal` only (advisor360 archived) | not-discharged |

## Root cause (established, not assumed)

`aitracker/term_gate.py:83` pinned the CLI's **old** refusal wording:

    "is currently running as a background agent (bg)"

The CLI now emits:

    Session <uuid> is running as a background session (<short>). Run `claude attach <short>` to
    open it, or `claude stop <short>` first to resume it here. Add --fork-session to branch off a
    copy instead.

So `term_gate.looks_like_bg_refusal()` returned False → `term_vt._resume_backstop()`
(`aitracker/term_vt.py` ~1877-1975) never reached its retry branch → the PTY sat on the refusal
forever. `term_gate.py`'s own docstring predicted this exact failure mode: a wording change
"degrades to no retry at all (a bare refusal shown to the user)".

**The control room did not introduce this.** `ext_cr_term.js` performs no terminal-output
inspection at all (its single pattern match is for `"too many running terminals"`); it delegates to
`ExtVT.mountInto()` and inherits whatever the shared seam does. The regression is a CLI wording
drift that disabled the seam for *both* UIs. The control room only made it visible.

Confirmed from `claude --help` on this machine, 2026-08-30:

    attach <id>        Open a background session in this terminal
    stop|kill <id>     Stop a background session. Its conversation is kept.

## The fix (shared seam — both UIs inherit)

- `term_gate.py` — `BG_REFUSAL_MARKERS` tuple matching both wordings; new `attach_target(output, sid)`
  (parses the short id out of the refusal's own `claude attach <short>` hint, falls back to
  `sid[:8]`) and `attach_argv(target)`.
- `term_vt.py` — `_retry_with_attach()` reusing the existing child-swap machinery; the backstop
  refusal branch tries attach first, falls back to the existing `_retry_with_fork()`. Attach is the
  *real* session, so no fork snapshot, no `forks.json` record, no `⑂ fork` chip.
- `term_launch.py` — the osascript shell chain becomes
  `(<resume> || <attach> || <resume --fork-session>)`.
- `docs/claude-resume-command-matrix.md` — re-captured verbatim wording, both eras.

Attach before fork because fork only ever produced a **copy**, which is why the user reported the
terminal "never really resumed".

## Adversarial review findings (two reviewers, opus + sonnet, run in parallel)

The opus reviewer ran the **real CLI against the real session from the screenshot** rather than
trusting any report. Captured live bytes under a pty with `CLAUDE_*` stripped:

    RC: ('EOF-then-exit', 1) at 4.51s | refusal matched at 3.69s
    REFUSAL_MARKER (old) in normalized: False      <- the bug, confirmed empirically
    "is running as a background session" in normalized: True
    attach_target(raw, sid) -> 'e30d3b6a'

This also established that the refusal genuinely **exits non-zero**, which is what makes the `||`
chaining in `term_launch.build_script` sound, and that the background agent runs in its own pgid,
so `Pty.kill()` on the attach client cannot take the user's agent down.

Three defects found and fixed:

1. **Wrong-session attach (security-adjacent, highest priority).** `attach_target` scraped
   `claude attach <token>` from the whole ~64KB pane buffer and preferred it over the clicked
   `sid` with no cross-check. A pane merely *quoting* a refusal for another session (a replayed
   transcript) would attach the user to a **different live agent**, with no `⑂` chip to signal it.
   Fixed: a scraped token is accepted only when `sid.startswith(token)` (case-insensitive); all
   matches are scanned, not just the first; the token regex is tightened to hex (`[0-9a-fA-F]{4,}`)
   so it cannot absorb arbitrary words; an unverifiable hint with no `sid` is refused (returns `""`,
   so the caller falls back to fork — a copy, which is safe — rather than attaching blind).
   **This defect originated in my own brief**: I instructed the test author to pin "hint wins over
   sid", so `test_prefers_parsed_hint_over_sid_when_they_disagree` enshrined the vulnerability. It
   was replaced by `test_hint_for_a_different_session_is_rejected_not_trusted`.
2. **`starting` cleared too early on the attach path.** `_retry_with_attach` cleared `pt.starting`
   as soon as the attach child was installed, before its fate was known, so a grid-renderer client's
   `done and not starting` terminating condition could close the EventSource mid-recovery.
   Reproduced 12/12 (near-deterministic on this machine; the reviewer saw 5/12). Fixed by leaving
   the flag to the backstop's fail-open `finally`, plus `not attach_tried` on the settle-clear — the
   latter was **necessary, not belt-and-braces**: `buf` keeps only the last `BACKSTOP_SCAN_BYTES`,
   so a chatty attach child pushes the refusal text out of the scanned tail and the settle fires by
   a second route. Now 0/12.
3. **A test spawned a real `claude` subprocess.** `test_refusal_plus_nonzero_exit_triggers_exactly_one_retry`
   mocked `_retry_with_fork` but not `_fork_child`, so with `sid="refused-sid"` it exec'd a real
   `claude attach refused-`. Slow, load-dependent, flaky, and on a dev machine capable of touching a
   real session. This was the source of the intermittent full-suite failures.

### Not a regression

`tests.test_term_run.TestSpawn.test_repo_local_config_cannot_run_a_program` failed once inside the
full suite. Verified 3/3 pass in the worktree **and** 3/3 pass on base `62178a1` in a throwaway
clone: load-dependent collateral from the stray real subprocesses above, not caused by this change.

### Parked (needs the user)

The load-bearing half — that the retry hands back the *real* session — has never been executed
live. Every `_retry_with_attach` test fakes `_fork_child`. Confirming it means running
`claude attach` against the user's own live working agent, which was deliberately not done while
they were away. One manual check closes it: `make serve`, resume a live background session, confirm
the pane shows the same session id still talking to the running agent.

## The `starting` trade, and how it was resolved

Fixing defect 2 by leaving `pt.starting` to the backstop's `finally` meant a *successful* attach
showed the grid client's "starting…" placeholder for the full `BACKSTOP_WINDOW` (measured 8.05s) —
itself a version of the reported complaint. Clearing it early at ~3s was rejected on measurement: it
reopens the same defect in miniature (a 3→8s window claiming "settled" while the fork fallback is
still armed).

Resolved with `ATTACH_SETTLE = 4.0` (`term_vt.py:1724`), which makes the backstop **return** once
the attach child has survived that long, so the flag's clearing and the end of recovery stay the
same instant and there is still exactly one clearing site. Placeholder drops to 4.17s, early closes
stay 0/12 at every attach lifetime tested.

Why 4.0: the analogous child (a refused `claude --resume`, same binary, same cold start) prints at
2.05s and exits at 2.61s; plus `BACKSTOP_POLL` lag the number to beat is ~2.7s. 4.0 leaves ~1.3s
(~50%) of margin, biased deliberately long because the failure directions are asymmetric — too
short costs a dead terminal (the original bug), too long costs a slightly longer placeholder.

Named cost: an attach that dies *later* than `ATTACH_SETTLE` no longer gets the fork fallback.
Bounded and documented in the constant.

An output-anchored settle was tried and does not work: `_feed_note` pushes its own line through
`_tee_raw` into the backstop's queue, so the re-armed clock anchors on our own injected note and
fires ~0.5s after the swap regardless of the child. That dead end is recorded in the constant's
docstring so it is not re-attempted.

## Verification

`TRACKER_AUTH= make check` → **1297 tests, OK, `selfcheck ok`, exit 0.**

Suite runtime dropped 378s → 191s once the real-`claude` exec was removed, and the unrelated
`test_term_run` flake disappeared with it (0 occurrences of the real-exec log line, down from 1).

Every new eval was proven RED before GREEN:

| Eval | RED against | Result |
|---|---|---|
| `test_current_wording_refusal_retries_with_claude_attach` | markers reverted to legacy-only | `[] != [['claude','attach','e30d3b6a']]` |
| `TestRegressionEval.test_current_message_is_recognised` | markers reverted to legacy-only | `False is not true` |
| `test_attach_leg_ordered_between_resume_and_fork_not_just_present` | attach placed after fork | `141 not less than 123` |
| `test_quoted_refusal_for_another_live_session_never_hijacks_the_click` | cross-check removed | `'e30d3b6a' != 'aaaaaaaa'` |
| `test_5_retry_with_attach_leaves_starting_set` | early clear reintroduced | `False is not true` |
| `test_1_pty_is_not_done_after_the_swap` | `pt.done = False` reset dropped | `True is not false` |

### Clause verdicts (final)

| # | Clause | Verdict |
|---|--------|---------|
| C1 | Resume terminal must stop hanging on the refusal | **discharged** |
| C2 | Replicate the earlier solved pattern / reuse the same seam | **discharged** — same backstop, same child-swap machinery |
| C3 | Use `claude attach <short>` rather than a fork copy | **discharged** — fork demoted to fallback |
| C4 | Add evals/tests so this cannot regress silently | **discharged** — 6 RED-proven evals; markers now pinned against verbatim captures |
| C5 | `make check` green | **discharged** — 1297 tests, selfcheck ok |
| C6 | `/tracker-push` — `personal` only | **discharged** — `b89a779` on `personal/main`, LICENSE ok |

### Still open

The live end-to-end run (`claude attach` against a real running background agent through the
browser) has not been executed — see "Parked" above. Everything else is proven.

### term_gate (sonnet) — DONE

Measured normalized output (backticks survive `_normalize_output`, so the plain-text regex works):

    Session e30d3b6a-046e-483b-b0f5-e0a1d692abfa is running as a background session (e30d3b6a). Run `claude attach e30d3b6a` to open it, or `claude stop e30d3b6a` first to resume it here. Add --fork-session to branch off a copy instead.

Verification run:

    looks_like_bg_refusal(current-CLI message)              -> True
    attach_target(current-CLI message)                      -> 'e30d3b6a'
    attach_argv(...)                                        -> ['claude', 'attach', 'e30d3b6a']
    looks_like_bg_refusal(legacy-CLI message)               -> True
    attach_target(unrelated, sid='abcdef1234567890')        -> 'abcdef12'
    attach_target(unrelated, no sid)                        -> ''
    attach_argv('')                                         -> []

Also verified against a true Ink column-jump rendering (words separated only by `\x1b[NG` cursor
jumps, no literal spaces) — normalization reinserts the spaces and both functions still match.
