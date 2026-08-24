# Terminal refusals — proposed fix direction

**Status:** for discussion. Nothing here is built. You asked to discuss the direction first.
**Grounded in:** [`docs/claude-resume-command-matrix.md`](claude-resume-command-matrix.md) — live
PTY tests against real sessions on this machine, not documentation or assumption.

## What the evidence actually says

| Session state | `--resume` | `--resume --fork-session` |
|---|---|---|
| Plain session (active or stale) | works, continues in place | works, **branches to a new session id** |
| Background agent (any status) | **refuses, exit 1** | works, opens the transcript as a new session id |
| Non-existent id | prints "No conversation found", then **starts a brand-new session** | n/a |

Three findings that decide the design:

1. **`--fork-session` works universally** — no error on plain sessions, no warning.
2. **There is no non-interactive attach.** `claude agents` is an interactive-only full-screen
   picker; `claude agents --json` lists (id, state, status, pid, cwd) but has **no attach verb and
   accepts no id**. Forking is the only programmatic route. My earlier suggestion that "attach is
   the better follow-up" was wrong.
3. **The permission-rule message is not a refusal.** The validator in the installed binary returns
   `{valid: true, warning: "..."}`. It is advisory; the session continues past it. **No fix needed.**

## The actual bug (not a policy question)

`aitracker/providers/claude.py:254` classifies background agents as `source == "sdk-cli"`. Tested
against two real background-agent sessions: **it matched neither.** Real ones carry
`"sessionKind": "bg"` in the JSONL.

So `term_gate.is_live_agent()` was asking the wrong question and always answered False — which is
why `--fork-session` never appeared. My earlier top-N theory was a real weakness but not the cause.

**This is wider than the terminal.** The same flag drives the 🤖 Agent badge in the sidebar, so the
app is mislabelling background-agent sessions everywhere. That makes it a `/tracker-gap` at the
provider seam, not a terminal patch — and it is a factual defect with a verified correct value, not
a choice. **Dispatched.**

## The policy question — this is what needs your call

Once detection is right, when should the terminal pass `--fork-session`?

**Option A — fork only background agents (my recommendation).**
Plain resume keeps continuing the real session in place, which is almost certainly what you want
when you click Resume on an ordinary session. Only the case that would otherwise refuse gets
forked. Cost: relies on detection being right — but detection is now verified against real logs and
will be pinned by a test.

**Option B — always fork.**
Dead simple, no detection in the path, cannot fail to fire. But it changes ordinary resume
semantics: every Resume click would branch to a new session id instead of continuing the one you
clicked. That silently multiplies your session list and is, I think, not what you want.

**Option C — try plain, detect the refusal, retry forked.**
Most robust: no reliance on classification at all, because the refusal itself is the signal. Costs
a failed spawn and a screen flash before the retry, and means parsing Claude's stderr text — which
will break silently the day the wording changes. I would avoid depending on a human-readable string.

**Recommendation: A, with C's refusal text as a safety net** — if a resume exits non-zero within a
second or two *and* the output matches the known refusal, retry once with `--fork-session`. That
way correct detection is the fast path and the string match is only a backstop, so a wording change
degrades to today's behaviour rather than breaking.

## What forking actually gives you

A **copy**. The transcript opens under a **new session id**; the original background agent keeps
running untouched. That is the only thing the CLI offers programmatically. Worth surfacing in the
terminal title so it is never mistaken for the live session — cheap to add, and it prevents the
confusion of editing a fork while expecting the original to move.

## Also worth deciding

**Non-existent ids currently start a brand-new session** rather than failing. If someone opens a
terminal on a session whose log was deleted, they silently get a fresh conversation instead of an
error. Probably worth refusing explicitly. Low priority, but it is the same class of surprise.
