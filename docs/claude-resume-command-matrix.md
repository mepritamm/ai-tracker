# `claude --resume` command matrix — empirically validated

Determined by running the real `claude` CLI (v2.1.241) against real sessions on this
machine (`~/.claude/projects/**/*.jsonl`) under a PTY harness, capturing the first few
seconds of output, and killing the process group. No session was left running. See
"Method" and "Cleanup" at the end.

## TL;DR — the matrix

| Session state | Command | Result | Recommended command |
|---|---|---|---|
| Plain session (not `--bg`), any age (active or stale) | `claude --resume <id>` | **Works.** Resumes normally, no warning. | `claude --resume <id>` |
| Plain session (not `--bg`), any age | `claude --resume <id> --fork-session` | **Works.** Opens a new session ID branched from the transcript. No error. | Use only if the user wants a branch; plain `--resume` is enough otherwise. |
| Background agent (`claude --bg`), any status (`blocked`, `done`, presumably `running`) | `claude --resume <id>` | **Refuses**, exits immediately with a non-zero code. Verbatim message below. | Don't use this alone. |
| Background agent (`claude --bg`), any status | `claude --resume <id> --fork-session` | **Works.** Opens the resumed transcript as a *new, independent* session ID; does not attach to/take over the live agent. | **This is the fix for the "currently running as a background agent" refusal.** |
| Non-existent session id | `claude --resume <id>` | Prints `No conversation found with session ID: <id>` **then falls through and starts a brand-new interactive session** in the current directory — it does not just exit. | n/a — treat as "start fresh," but tell the user the id was wrong. |
| (n/a) | `claude agents` (bare) | **Interactive-only** full-screen picker/dashboard (columns: "Needs input" / "Ready for review" / "Completed"). Takes no id argument. Not scriptable. | Use for a human to browse, not for a script. |
| (n/a) | `claude agents --json` | **Non-interactive**, exits immediately, no TTY required. Prints every session (`kind: "interactive"` or `"background"`) with `sessionId`, `state`, `status`, `pid`, `cwd`, `name`. **Does not attach to anything** — read-only listing. | Use this to *look up* the id, then `claude --resume <id> --fork-session` to actually open it. |

## Ground truth per question the user asked

**Is there a non-interactive way to attach to a live background agent?**
No. `claude agents --json` is the only non-interactive command touching background
agents, and it only *lists* them (id, state, status, pid, cwd, name) — it has no
attach/id argument. `claude agents` (bare) is a full-screen interactive picker with no
id argument either (confirmed by observing it live: a dashboard with a
"describe a task for a new session" prompt box, navigated by arrow keys). The only way
to actually open a background agent's transcript is `claude --resume <id>` (which
refuses) or `claude --resume <id> --fork-session` (which works). There is no
`claude agents attach <id>` or equivalent.

**Does `--fork-session` work on a non-agent session too, or does it error?**
It works, no error, on every session state tested: plain sessions (fresh or weeks
stale) and background-agent sessions alike. `--fork-session` is universal — it always
produces a new session id branched off the given transcript rather than reusing the
original id. The CLI's own `--help` text confirms this is its designed purpose ("When
resuming, create a new session ID instead of reusing the original"), not something
specific to background agents.

**Is the permission-rule warning fatal, or does the session continue past it?**
**Not fatal — it is only a warning.** This was established directly from the installed
CLI binary (`/Users/pritammondal/.local/share/claude/versions/2.1.241`, a compiled
bundle) rather than by guessing. The exact validation function was found via `strings`:

```
return{valid:!0,warning:`${Ld(o)} is not matched by file permission checks — only
${a}(path) rules are. Use ${Ld({toolName:a,ruleContent:o.ruleContent})} instead
(${a} rules cover all file-${a==="Edit"?"editing":"reading"} tools).`}
```

`valid:!0` is `valid: true` in the minified JS. The function returns a *valid* result
that merely carries an advisory `warning` string — it is not a rejection, and nothing
in this code path throws or exits. Separately, this was cross-checked live: a scratch
directory with `.claude/settings.json` containing `"allow": ["Write(../repos/**)"]`
was opened with plain `claude` (no prompt sent). The startup trust dialog showed:

```
⚠ This folder pre-approves 1 tool permission in .claude/settings.json:
  Write(../repos/**)
These will apply without asking. Only proceed if you trust this configuration.
```

i.e. the session starts up fine and treats the rule as present; it just won't function
as a path-scoped auto-approval for `Write` the way it would for `Edit`. **Caveat: I did
not drive a real prompt to the point where the agent actually attempts a `Write` call**
(that would spend real quota), so I did not directly observe the exact wording/timing
of the warning as it appears mid-session, only the settings-validator's `valid:true`
return value and the equivalent startup-time trust-dialog acknowledgment. I'm confident
in "not fatal" from the `valid:true` code path; the *exact point in the session* where
the warning text prints is the one thing I could not fully pin down live.

**What does `--resume` do with a non-existent id?**
Prints `No conversation found with session ID: <the id>` and then continues into a
**fresh, brand-new session** in the current directory (visible from the MCP server
initialization spam — "Client.listTools() called..." — that follows). It does not just
exit. This matters: a caller that only checks "did it print an error" and doesn't also
watch for a still-running interactive process could mistakenly think the resume failed
cleanly, when actually a brand-new (uninitialized) session is now sitting open.

## Session states found on this machine, and how they were classified

| Label | Session id | mtime | How classified | cwd |
|---|---|---|---|---|
| Background agent (bg, done) | `eb5db9b4-4c93-41ab-9b2d-1b7c08518dc8` | 2026-08-24 17:56 (~20 min before testing) | `"sessionKind":"bg"` in the `.jsonl`; `claude agents --json` shows `"kind":"background", "state":"done", "status":"idle"` | `.../VIDA20/dw-vida-stack` |
| Background agent (bg, blocked/awaiting input) | `e4e6bdd6-937b-4b4a-ac2f-9a8c7789e5b7` | 2026-08-24 18:08 (~8 min before testing) | same as above; `claude agents --json` shows `"state":"blocked"` | `.../VIDA20/dw-vida-stack/.claude/worktrees/vida-audit-bot-handover` |
| Interactive, most-recently-touched non-bg | `01e1d3a3-f1ed-4e88-9858-0256c0a51bee` | 2026-08-24 15:28 (~2h48m before testing) | `claude agents --json` `"kind":"interactive"`, no `sessionKind:"bg"` field in the jsonl | `.../VIDA20` |
| Interactive, stale (weeks old) | `5bf2fba9-987a-4c1f-b3ee-e88460321543` | 2026-07-27 13:21 (~4 weeks before testing) | no `sessionKind` field; ordinary `entrypoint:"cli"` | `.../ai-tracker` |
| Non-existent (control) | `00000000-0000-0000-0000-000000000000` | n/a | doesn't exist | n/a |

**On "ACTIVE within the last few minutes":** at the moment of testing, the *only*
session on this machine with an mtime inside the last few minutes was the parent
orchestrator session that spawned this research task itself
(`eed23597-5bd0-48d6-9974-fad5fca57ad4`, confirmed via `ps aux` to be a live process
actively resumed by the Claude Desktop app plus several of its own live subagent
forks). I deliberately did **not** run any test command against that id — doing so
risked interfering with the user's own live orchestrator process and its subagents.
The next-freshest genuinely interactive (non-bg) session was ~2h48m old
(`01e1d3a3...`), so that stood in for "recently active." This is a limitation of
testing against a real, in-use machine rather than a guess — noted rather than
glossed over.

## `ai-tracker`'s own background-agent detection does not match this reality

`aitracker/providers/claude.py:254` flags a session as a background agent when
`source == "sdk-cli"` (i.e. the jsonl's `entrypoint` field, read at
`aitracker/providers/claude.py:123`). On this machine, grepping every `.jsonl` under
`~/.claude/projects` found:

- `entrypoint` values in use: `"cli"`, `"claude-desktop"`, `"sdk-cli"`.
- The two confirmed real `claude --bg` background-agent sessions used in this test
  (`eb5db9b4...`, `e4e6bdd6...`, both reproducing the exact "currently running as a
  background agent" refusal) both have `entrypoint:"cli"`, **not** `"sdk-cli"` — the
  actual marker distinguishing them is a *different* field, `"sessionKind":"bg"`.
- Every session found with `entrypoint:"sdk-cli"` on this machine was either a pytest
  fixture under `/private/var/folders/.../pytest-of-pritammondal/...` or a session in
  an old, now-abandoned `bug-smasher` worktree — none had `"sessionKind":"bg"`, and
  none triggered the "currently running as a background agent" refusal when resumed
  (not individually re-tested for all of them, but the field pattern strongly suggests
  `sdk-cli` entrypoint means "this session was launched by some Claude Agent SDK
  program," which is a different thing from `claude --bg`).

This is a **factual finding, reported as requested, not a fix** (this task made no
code changes): ai-tracker's `source == "sdk-cli"` check does not identify the sessions
that actually produce the "currently running as a background agent" refusal on this
machine. The real discriminator observed here is `"sessionKind":"bg"` in the jsonl (or
equivalently, showing up with `"kind":"background"` in `claude agents --json`).

## Verbatim captured output

### `claude --resume <id>` on a background agent (blocked state) — refuses, exits immediately

```
Session e4e6bdd6-937b-4b4a-ac2f-9a8c7789e5b7 is currently running as a
background agent (bg). Use `claude agents` to find and attach to it, or add
--fork-session to branch off a copy.
```
Process exit status: `EXITED code=1` (self-terminated — did not need to be killed).

### `claude --resume <id>` on a background agent (done state) — identical refusal

```
Session eb5db9b4-4c93-41ab-9b2d-1b7c08518dc8 is currently running as a
background agent (bg). Use `claude agents` to find and attach to it, or add
--fork-session to branch off a copy.
```
Same message verbatim, confirming the refusal fires regardless of whether
`claude agents --json` reports the agent's `state` as `"blocked"` or `"done"` — only
`sessionKind:"bg"` seems to matter, not whether the agent is still actively working.

### `claude --resume <id> --fork-session` on the same background agent — succeeds

Opened the actual resumed transcript (the audit-bot session's real conversation
content, including its last assistant turn, a recap block, the `/effort` and mode
status line, and an active input prompt). Reached a fully interactive, idle prompt —
had to be `SIGKILL`ed (`SIGTERM` alone was not enough; the fullscreen TUI appears to
trap/ignore it while in raw terminal mode). No refusal text appeared anywhere in the
captured output.

### `claude --resume <id>` on a non-existent id

```
No conversation found with session ID: 00000000-0000-0000-0000-000000000000
```
Then immediately proceeds to boot a **new** session (repeated
`Client.listTools() called but server does not advertise tools capability — returning
empty list` MCP-init lines followed).

### `claude --resume <id>` on a plain (non-bg) stale session — works, no warning at all

Resumed successfully; showed the CLI banner (`Claude Code v2.1.241`,
`Opus 5 (1M context) with high effort · Claude Max`), the cwd, and then the full prior
transcript, landing at an interactive idle prompt. (Output not reproduced verbatim
here beyond the banner — the transcript contained the user's real, private
conversation about adding a GitHub collaborator, including a masked token and a real
email address, which does not belong in this report.) No refusal or warning of any
kind appeared.

### `claude --resume <id> --fork-session` on that same plain stale session — also works

Same successful resume behavior as above; `--fork-session` produced no error and no
different behavior from the caller's perspective other than (per `--help`) using a new
session id under the hood.

### `claude agents` (bare) — confirmed interactive-only

```
40 awaiting input · 0 working · 59 completed

Ready for review
∙ audit bot rel-aug26 configuration    dw-Integration Layer API…   6 PRs  5m

Needs input
✻ audit-bot          choose: wrap all git/g…            #7801   d
✻ AIO-2925           say the word and I'll…             ⧉      15d
... [17 more rows, real session names/ids from this machine] ...

Completed
… 80 more

────────────────────────────────────────────────────────────────
❯ describe a task for a new session
────────────────────────────────────────────────────────────────
enter to collapse · ctrl+x to delete all · ? for shortcuts
```
This is a full-screen dashboard requiring keyboard navigation; it takes no session-id
argument on the command line and cannot be scripted. Had to be `SIGKILL`ed.

### `claude agents --json` — confirmed non-interactive, exits on its own

Returns immediately (`timeout 10` was not needed) with a JSON array of every known
session — interactive and background — each with `id` (short), `sessionId` (full
uuid), `kind` (`"interactive"` / `"background"`), `state` (`"blocked"` / `"done"` /
absent for interactive), `status`, `pid`, `cwd`, `name`, `startedAt`. 46 entries were
returned on this machine at test time; `states` breakdown was `{"blocked": 40, "done":
2, (interactive/no state): 4}` — no entry was observed with a `"running"` state, i.e.
nothing was mid-turn-executing at the moment of the snapshot.

### Relevant `claude --help` flags (quoted verbatim)

```
--bg, --background                    Start the session as a background agent
                                       and return immediately (manage with
                                       `claude agents`)
--fork-session                        When resuming, create a new session ID
                                       instead of reusing the original (use
                                       with --resume or --continue)
-c, --continue                        Continue the most recent conversation in
                                       the current directory
-r, --resume [value]                  Resume a conversation by session ID, or
                                       open interactive picker with optional
                                       search term
--from-pr [value]                     Resume a session linked to a PR by PR
                                       number/URL, or open interactive picker
                                       with optional search term
--teleport [session]                  Resume a teleport session, optionally
                                       specify session ID
--no-session-persistence              Disable session persistence - sessions
                                       will not be saved to disk and cannot be
                                       resumed (only works with --print)
--session-id <uuid>                   Use a specific session ID for the
                                       conversation (must be a valid UUID)
```

`claude agents --help` (verbatim, relevant flags):

```
Usage: claude agents [options]

Manage background agents

Options:
  --all                                 With --json: also include completed
                                        background sessions
  --cwd <path>                          Show only background sessions started
                                        under <path>
  --json                                Print active sessions (interactive and
                                        background) as a JSON array and exit
                                        (for scripting; does not require a TTY)
```
No `agents` subcommand or flag accepts a session id to attach; `agents` has no `attach`
verb. (`--all` with `--json` was not separately tested — noted below as not
determined.)

## What I could not determine

- The exact wording/timing of the `Write(../repos/**)` permission warning **as it
  appears mid-session** when the agent actually attempts a matching tool call. I
  established from the binary that the validator returns `valid:true` (not fatal) and
  observed the equivalent trust-dialog acknowledgment at startup, but did not drive an
  actual `Write` tool call to see the live warning text print in context, to avoid
  spending real API quota on a throwaway scratch-directory session.
- Whether `claude --resume <id>` on a background agent whose `state` is genuinely
  `"running"` (mid-turn, actively executing) behaves identically to the `"blocked"` and
  `"done"` cases tested here. No session on this machine was in a `"running"` state at
  test time (`claude agents --json` showed 0 such entries), so this specific state was
  not directly observed — only inferred from the fact that the refusal fires purely off
  `sessionKind:"bg"`, independent of `state` for the two states that were available.
- Whether `claude agents --json --all` surfaces anything materially different (e.g.
  additional completed sessions) — not separately tested.
- Whether a *short* 8-character id (the `"id"` field `claude agents --json` prints,
  e.g. `eb5db9b4`) is accepted by `--resume` the same way the full UUID is — not
  tested; all tests here used the full `sessionId`.

## Method

All `claude` invocations that could open an interactive session were run under a
custom PTY harness (`pty.openpty()` + `subprocess.Popen(..., preexec_fn=os.setsid)`)
that captured output for 4–8 seconds and then sent the whole process group `SIGTERM`,
escalating to `SIGKILL` after 0.5s if still alive. `claude --help`, `claude agents
--help`, and `claude agents --json` were run as plain (non-PTY) subprocesses since they
exit on their own and explicitly don't require a TTY. `zsh -l` was avoided throughout;
`claude` was exec'd directly.

## Cleanup / verification that nothing was left running

After every test, the specific pid captured by the harness was checked with `ps -p
<pid>`. All ten pids spawned during this investigation
(18930, 19045, 19143, 19239, 19337, 19499, 19663, 19775, 19882, 20153) were confirmed
gone by the end of the session. A final broad `ps aux | grep claude` was also run and
cross-checked against every session id used in testing
(`e4e6bdd6`, `eb5db9b4`, `5bf2fba9`, `01e1d3a3`, the all-zero control id) — no matches
remained. The three unrelated `claude` processes still running at the end
(pids 14807, 14905, 14967, all started 18:14:55–58, i.e. before this investigation's
first test at ~18:16:35) are other, pre-existing sibling sessions under the same
parent orchestrator and were not touched. `make serve` was never run; no
`aitracker/**`/`tests/**` files were modified; this document is the only write inside
the repo.
