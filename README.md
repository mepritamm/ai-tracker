# AI Session Tracker

A zero-dependency, local web dashboard that shows you **what your AI coding sessions are doing — live**, across tools. It reads the session logs each AI coding tool already writes to disk and turns them into one readable view: a plain-language summary, todos, files touched, commands run, background agents/shells, and the assistant's own narration — refreshing every 2 seconds.

Works across tools via a small **provider** for each. Built in today: **Claude Code** and **Auggie / Augment**. Adding another is a ~2-function adapter (see [Adding a tool](#adding-a-tool)).

Nothing is sent anywhere. It's a single Python file using only the standard library, serving a local page you open in your browser.

<p align="center">
  <img src="docs/screenshot.png" alt="AI Session Tracker — live dashboard showing the session sidebar, a plain-language summary, background agents, and the assistant's narration" width="880">
</p>

<p align="center"><sub>Live dashboard — session sidebar, summary (Goal / Now / So far), stat chips, background agents & shells, and the assistant's own narration.</sub></p>

---

## Installation

**Prerequisites:** **Python 3.8+**. That's it — the app is a single file using only the Python standard library, so there is **nothing to `pip install`** and no build step.

**Get the code:**

```bash
git clone https://github.com/mepritamm/ai-tracker.git
cd ai-tracker
```

(or just grab the standalone `dist/tracker.py` from a `make bundle` — one file, no install).

**Nothing else to configure.** The tracker auto-discovers your local session data:

- **Claude Code** → `~/.claude/projects/**/*.jsonl` (Desktop, CLI, and VS Code)
- **Auggie / Augment** — three surfaces:
  - **Auggie CLI** → `~/.augment/sessions/*.json`
  - **Augment VS Code** extension → `~/Library/Application Support/Code/User/workspaceStorage/**/Augment.vscode-augment/`
  - **Augment Cursor** extension → `~/Library/Application Support/Cursor/User/workspaceStorage/**/Augment.vscode-augment/`

A tool only appears if its data exists on the machine — install nothing, it just lights up what you already have.

---

## Quick start

```bash
python3 -m aitracker
```

That's it. It starts a local server on **http://localhost:8787** and opens your browser. Pick a session from the sidebar (or paste a session id) and watch it work. If `8787` is already taken it automatically uses the next free port (and prints the one it picked, plus records it in `aitracker/port` so the notes drain hook can still find it).

Prefer the Makefile — it restarts cleanly (frees a stuck port so UI changes always take effect):

```bash
make serve            # run locally on http://localhost:8787 — no tunnel, no login (the default)
make stop             # stop the tracker (and any running tunnel)
make serve PORT=9000  # use a different port
make tunnel           # OPTIONAL — reach it from your phone via a Cloudflare tunnel (needs TRACKER_AUTH; see below)
make check            # the gate: --selfcheck + unit tests (must be green)
make test             # just the unit-test suite
make hooks            # install the pre-commit gate (blocks commits that fail check)
```

Flags: `python3 -m aitracker --version` · `--help`. Set a port without the Makefile: `PORT=9000 python3 -m aitracker`.

To keep it running in the background: `nohup python3 -m aitracker >/tmp/tracker.log 2>&1 &`.

**Local by default.** `make serve` binds to `localhost` only, with no login — nothing leaves your machine and no tunnel is involved. Reaching it from a phone is entirely **opt-in** (`make tunnel`, or the other options in the guide below); until you choose one, it stays localhost-only.

---

## View it on your phone or tablet

Locally it's just `make serve` (localhost, no tunnel, no login). To reach it from a phone, pick a connectivity option — a free **Cloudflare tunnel** (`make tunnel`; works through most corporate firewalls where ngrok/Tailscale are blocked), a private **Tailscale** mesh, an **ngrok** tunnel, or your **LAN** — then install it as a home-screen app (fullscreen, responsive phone/tablet layout) and require a password with `TRACKER_AUTH`. It's all opt-in — the tracker stays localhost-only until you choose one.

**→ [Remote & mobile access setup](docs/remote-access.md)**

---

## Terminal — opt-in, off by default

The tracker normally only *reads*. Three features let it *start processes*, so all are off unless you set **`TRACKER_TERMINAL=1`** **and** a **`TRACKER_AUTH`** login — either alone does nothing.

```bash
TRACKER_TERMINAL=1 TRACKER_AUTH=user:pass make serve
```

- **Terminal in the browser** — **▶ Open terminal here** and **▶ Resume in terminal** open a real interactive terminal in a dialog, right in the page: a live PTY in the session's working directory, `claude --resume <id>` for the resume variant. It runs full-screen programs — `vim`, `top`, Claude Code's own TUI — because the VT100/xterm emulator lives *server-side* in Python (stdlib only; nothing is vendored into the page). **⤢ New tab** reopens the *same* shell full-window in its own browser tab, so you can leave it running alongside the dashboard.
- **Open in Terminal/iTerm instead** — the `↗` buttons launch your real macOS terminal app (`TRACKER_TERM_APP` picks Terminal or iTerm) `cd`'d to the session's directory. Local machine only; hidden when you're not on localhost. Resume is Claude-only; other tools get the `cd` alone.
- **Command runner** — runs line-oriented commands (`git status`, `make check`, `npm test`, …) in the session's directory and streams the output into the page with colour. There is **no shell**: the command is `shlex.split` into argv and `execvp`'d directly, so shell metacharacters are never operators. Commands must match an argv-prefix allowlist, overridable with `TRACKER_TERM_ALLOW`. Output is capped, concurrent jobs are capped, and a job is killed when you close its view.

### What these features do and don't guarantee

Worth reading before you enable them over a tunnel.

- **The in-browser terminal is an unrestricted shell, and it is reachable wherever the server is.** No allowlist applies to it — that is the whole point of the feature. There is deliberately **no loopback restriction**: it works over `make tunnel` on purpose. So with `TRACKER_TERMINAL=1`, anyone who can reach the port and knows `TRACKER_AUTH` gets a shell as your user. **Treat `TRACKER_AUTH` with the seriousness you'd give a root password**, and rotate it if you expose it publicly.
- **"Local only" on the `↗` buttons is best-effort, not a guarantee.** That route refuses requests carrying a proxy's fingerprint (`X-Forwarded-For` and friends) and non-loopback peers. But `make tunnel` terminates on this machine and dials the server over loopback, so a peer address proves nothing on its own. The thing actually standing between a stranger and your machine is `TRACKER_AUTH`.
- **"No shell" is not "no code execution."** The allowlist deliberately includes commands that run project-supplied code: `make` runs your `Makefile`, `pytest` imports your `conftest.py`, `npm test` runs your scripts. That is the point of the feature, not a bug — but it means the runner is as trustworthy as the directory it runs in.
- **Running `git` inside a repository whose `.git/config` you don't control is code execution, by git's own design.** The runner neutralises the vectors it knows (external diff and textconv drivers, `core.fsmonitor`, `core.hooksPath`, pagers, `core.editor`) and refuses config-bearing flags, but git has many config-driven exec points and that list is not proven complete.
- **`cat` and `ls` are confined** to the session's own directory, so they can't read your keys.

---

## What it shows

**Sidebar** — every session across all your tools and projects, newest first, each with a source badge (Claude Desktop / Claude CLI / Claude SDK / Claude VS Code / Auggie / Augment VS Code / Augment Cursor), a live dot, and a short title.
- **Background-agent sessions** (SDK-spawned, e.g. into a git worktree) are marked **🤖 Agent** and folded into a collapsible **🤖 Agents · &lt;repo&gt;** group per repo — so they don't bury your own sessions in the flat list. Click the group to expand its agents.
- A session running **in-transcript background agents** (Task/Workflow subagents — which spawn no separate session) carries a **🤖 N running** badge, so you can see it's busy without opening it.
- **End-state at a glance** — a session **waiting on your answer** (an unanswered `AskUserQuestion` / Auggie `ask-user`) is flagged **⏳ answer** with an amber highlight so you know to go respond; one that **just completed its last run** (the last turn was the assistant finishing, within the live window) shows a subtle **✅ done** — gated to fresh completions so it flags what just landed rather than every stale session. Both work for every tool.
- **Click "N live"** to filter to only active sessions (live = touched in the last 5 minutes).
- **Search** by keyword — matches your prompts and the conversation (not the boilerplate); sessions whose *name* matches rank first.
- **✎ rename** any session to a title that means something to you (saved to `titles.json`).
- **📌 pin** any session to keep it at the top of the list, above recency (saved to `pins.json`).
- Sessions with notes show a **📝 N** badge (see the Plan-on-the-go panel below).
- Sessions with open flags show a **🚩 N** badge and a red edge, and the sidebar's own **🚩** button (next to the 🔔 bell) opens **every session's flags in one list** — each row names the session it belongs to and clicks through to it. Without it, a flag raised on a session you aren't currently looking at is invisible. Resolve / reopen / delete work from that list too, on any screen size.

**Main view** for the selected session — the header carries a progress ring, title, stat chips, a **🔍 search-this-session** toggle, and a **🚩 Flag an issue** toggle; below it the body splits into two halves, **◐ State** (progress, PRs, plan, decisions, summary) and **◑ Activity** (narration, prompts, files, commands), collapsing to one column on narrow screens. Every panel collapses to just its header — click the title (or the **▾/▸** chevron) to fold a panel away and focus on what you care about. A **☀️/🌙 theme toggle** next to the 🔔 bell switches between the default dark and a warm-beige light mode (remembered across visits); background agents & shells live in a right-side drawer. The 🚩 Flags panel is opt-in — the header toggle reveals it above the State/Activity split, and it opens by itself when the session you're viewing has an open flag.
- **Search within the open session** — the header **🔍** button reveals a full-width search card above the State/Activity split (like the Flags panel). It matches across this session's narration, prompts, files, commands and todos in one place; each hit shows a highlighted snippet and clicks through to the same pop-out modal (diff for files, output for commands, full text otherwise). Works for every tool.
- **Waiting, not idle** — when a session stopped on an unanswered question, the header reads **⏳ waiting on you · &lt;age&gt;** (amber) instead of "idle", and the banner says *Waiting on your answer*. Same signal as the sidebar's **⏳ answer**, so a blocked session never reads as merely stale. Works for every tool.
- **Session summary** — Goal, what it's doing *Now*, and a one-line "So far", with stat chips (files, commands, reads, commits, tests, tokens, git branch).
- **Decisions & open questions** — every question the session asked you (Claude `AskUserQuestion` / Auggie `ask-user`) with its options; **open** ones (awaiting your answer) are flagged and pinned to the top, decided ones show the choice you made. It's view-only — answer in the actual session (the tracker never writes to it).
- **Background agents & shells** — running ones shown; finished ones one click away. Click one to read its full prompt and narration/output; while it's still running that view stays live, refreshing in place every 2 s. A repo's spawned **agent sessions** are listed here too (with their worktree name) — live ones shown, finished ones behind a **Show N finished** disclosure — click **open ›** to jump straight into that agent's own session. Re-runs of the same agent (identical task) collapse into one row tagged **×N**, opening the latest run — so the count reflects distinct agents, not every retry. When one completes you get a toast + sound, plus a desktop notification if the tab is in the background (so you're alerted even while working elsewhere — allow notifications on first click; toggle with the 🔔 bell). *(Claude Code only — Auggie has no background-work model.)*
- **Pull requests** — the PRs a session actually *generated* (created via `gh pr create` or the GitHub MCP tool), as clickable links; PRs it merely referenced are left out. This includes PRs opened by the session's **background agents** — a subagent's `gh pr create` is attributed to the session and tagged **🤖 agent**, so agent-generated PRs don't vanish with the subagent. Each carries a **merged**/**closed** badge when the session's own logs reveal that state (a `Merge pull request #N` in git-log output, `gh pr merge/close N`, or the GitHub MCP merge) — so a landed PR no longer reads as perpetually "open"; otherwise it shows as open.
- **Narration** — the assistant's own words, step by step, with full markdown rendering (tables, code, lists) in the pop-out modal — each code block has its own one-click **⧉ Copy** button, and a ` ```mermaid ` fence is drawn as an actual **diagram** instead of raw source. The renderers cover the diagram families that actually turn up in agent-generated markdown, so a `stateDiagram-v2` or `classDiagram` no longer lands as raw code beside a rendered flowchart: **flowcharts** (`flowchart`/`graph` — node shapes, edge labels, `classDef` colours), **sequence diagrams** (`sequenceDiagram` — participants, messages, self-loops, `Note over`/`left of`/`right of`, `alt`/`opt`/`loop`/`par` blocks with nesting), **state diagrams** (`stateDiagram`/`stateDiagram-v2` — states, `[*]` pseudostates, labelled transitions, aliased states, composite states flattened), **class diagrams** (`classDiagram` — classes with members, every relationship kind, cardinality on the edge), **ER diagrams** (`erDiagram` — entities with attributes, cardinality translated to readable prose), **user journeys** (`journey`/`userJourney` — sections with tasks and happiness-score faces), **pie charts** (`pie` — labelled slices with legend and percentages), and **quadrant charts** (`quadrantChart` — 2×2 axes with plotted points). Any other diagram type still shows as code, but tagged (🧜 mermaid: `gantt`, `mindmap`, `timeline`, `gitGraph`, `xychart-beta`, …) so the intent is visible rather than mistaken for a plain code fence. Rendered locally in plain SVG — no mermaid.js, no CDN, still zero dependencies. This holds anywhere markdown is rendered: narration, prompts, todos, notes, agent/shell output and the Rendered-markdown view of a `.md` file. Plus prev/next arrows and a jump-to-latest (⤒) button across every entry. History is unbounded — older entries page in from the server as you scroll. An open entry stays live: it follows the newest message, or holds your place if you've paged back into history.
- **Todos**, **Files** (a diff per edit, with GitHub-style **up/down context expansion** and an **Expand all** toggle to reveal the whole file around every edit, plus a Diff ⇄ Rendered-markdown toggle and an "open in new tab" button), **Commands** (with ✓/✗ for Claude), and **Prompts** (every prompt you typed, slash-command invocations like `/foo args` included). Files a background agent wrote — e.g. editing inside a git worktree — show too, tagged **🤖 agent**, and stay diffable.
- Every list panel loads a window and reveals older entries as you scroll to the bottom.
- **🧭 Plan on the go** — a per-session stack of small plan-ahead notes: jot what you want to do once an answer lands (or while you wait on another session), and it stays with the session. Add as many as you like; **copy** one back when you need it, **push** it into the live session, **remove** it when done.
  **▶ push** queues a note for delivery and the session collects it itself, so you never have to interrupt it or paste anything. The chip tells you *when* it will land, because that depends on what the session is doing: a **live** session picks it up the moment it finishes its current turn (**⏳ queued**); an **idle** one has no turn to finish, so it lands the next time you prompt or resume it (**⏳ queued · on wake**); a tool with no hook at all just holds it (**⏳ queued · copy it**). Delivery needs hooks — Claude Code has them; wire [`hooks/drain-notes.py`](hooks/drain-notes.py) into `Stop`, `UserPromptSubmit` and `SessionStart` (instructions in the file) and pushed notes arrive on their own. `Stop` alone only ever reaches a session that's mid-turn. Hooks are spawned by the AI tool, not by your shell, so they can't inherit your port or `TRACKER_AUTH` — the server writes both to `aitracker/port` and `aitracker/token` (owner-only) and the hook reads them. If a pushed note stays stuck at **⏳ queued**, read `aitracker/drain.log`: delivery is silent toward the session on purpose, but every *failed* attempt says why there. Tools without hooks (Auggie today) still queue, but you deliver by **⧉ copy**. Sessions with notes carry a **📝 N** badge in the sidebar. Saved to `notes.json`, read live (no restart). Works for every session, any tool — and you can add notes from your phone or tablet too, just like 🚩 flagging.
- **🚩 Flag** anything you want to fix later — see [Skills](#skills).

---

## How it works

Every supported tool writes an append-only session log to disk. The tracker only ever **reads** those files — there's no integration, no API key, and no network traffic.

1. **Serves** a single self-contained HTML page (`GET /`).
2. **Parses** a session's log on demand (`/api/session?id=…`) into one structured view.
3. The browser **polls** every 2 s — that re-read is the "live".

Each tool plugs in as a **provider** (a small adapter). The registry — `PROVIDERS` in `aitracker/registry.py` — merges every available provider's sessions into one list and routes each session id (namespaced by prefix, e.g. `auggie:`) to the adapter that owns it. One broken provider can't sink the list.

All providers emit the **same result shape**, so the browser renders them identically. Where a tool records the data, the tracker surfaces it:

| Data | Claude Code | Auggie CLI | Augment VS Code / Cursor extension |
|------|-------------|------------|------------------------------------|
| Summary, todos, prompts, narration, files, tokens | ✅ | ✅ | ➖ **todos + files touched only** — the chat transcript lives in a per-workspace LevelDB (`augment-kv-store`) the tracker can't read stdlib-only. The narration panel says so honestly, then shows what IS on disk. |
| Commands, reads, commits, tests | ✅ | ✅ (from `launch-process` / `view` tools) | ➖ (in LevelDB, same reason) |
| Working folder + git branch (worktree-aware) | ✅ (from the log) | ✅ (folder from IDE state; branch from `.git/HEAD`) | ✅ folder (from `workspace.json`); ➖ branch |
| Command exit status (✓/✗) | ✅ | ➖ Auggie stores none — commands show as ✓ | ➖ n/a |
| Pull requests — created **or** worked on | ✅ (created via `gh pr create` / MCP; worked-on = narrated about **and** in the session's own repo) | ✅ (Auggie logs no command output, so a created PR is tied to the first URL after `gh pr create`; worked-on = narrated about **and** in its own repo) | ➖ n/a |
| Decisions & open questions | ✅ (`AskUserQuestion`) | ✅ (`ask-user` — answer from the next turn's tool result) | ➖ n/a |
| Background agents & shells | ✅ | ➖ Auggie has no such model | ➖ n/a |
| Markdown rendering, incl. ` ```mermaid ` fences drawn as diagrams | ✅ | ✅ (shared renderer — one seam, both sources) | ✅ (same shared renderer) |
| 📝 Notes — write, ⧉ copy, 📝 N badge | ✅ | ✅ | ✅ |
| ▶ push a note into the session | ✅ live → next turn-end; idle → next prompt/resume (`Stop` + `UserPromptSubmit` + `SessionStart` hooks) | ➖ queues fine, but Auggie has no hooks to deliver it — use ⧉ copy | ➖ same — no hook, use ⧉ copy |

**Data files** — `flags.json` (your flags), `titles.json` (your renames), `pins.json` (pinned sessions), and `notes.json` (your notes) are read **live** (no restart). Everything else is baked into the page at startup, so **editing `aitracker/` or `web/` needs a server restart** to show.

---

## Supported tools

| Tool | Source on disk | Status |
|------|----------------|--------|
| **Claude Code** (Desktop / CLI / VS Code) | `~/.claude/projects/**/*.jsonl` | ✅ built in |
| **Auggie CLI** | `~/.augment/sessions/*.json` | ✅ built in |
| **Augment VS Code extension** | `~/Library/Application Support/Code/User/workspaceStorage/**/Augment.vscode-augment/` (JSON) + LevelDB (skipped) | ✅ built in (todos + files touched; chat transcript degraded — see the parity table above) |
| **Augment Cursor extension** | `~/Library/Application Support/Cursor/User/workspaceStorage/**/Augment.vscode-augment/` (JSON) + LevelDB (skipped) | ✅ built in (same as VS Code) |
| Cursor's own AI, OpenAI Codex | SQLite databases | ⚙️ needs an adapter (format-specific reader) |
| GitHub Copilot CLI | binary LMDB blobs | ⚙️ needs an adapter |

Only tools that keep a **readable local transcript** can be adapted. Claude, Auggie CLI, and the JSON portion of the Augment extensions write plain JSON/JSONL; others use SQLite or binary stores that each need their own reader (the extensions' chat transcript is one such binary store — LevelDB — which is why those two rows sit at partial parity rather than full).

## Adding a tool

Write one `Provider` in `aitracker/providers/` and register it in `aitracker/registry.py` — no core changes:

```python
class MyToolProvider(Provider):
    prefix = "mytool:"                     # namespaces this tool's session ids

    def available(self):                   # is the tool's data on this machine?
        return os.path.isdir(MY_TOOL_DIR)

    def list(self):                        # -> session summaries for the sidebar
        # return [{ "id": "mytool:<id>", "title", "project", "source": "mytool",
        #           "mtime", "prompt", "cwd" }, ...]
        ...

    def parse(self, sid):                  # full id -> the detail view dict
        # return the same shape parse_session()/parse_auggie() return
        ...

    def search(self, q):                   # optional keyword search
        return []

PROVIDERS = [ClaudeProvider(), AuggieProvider(), MyToolProvider()]
```

Add its source label to the `SRC` map in the page (e.g. `"mytool": "◆ MyTool"`) and it shows up with a badge, live status, search, and the full session view — same as the built-in tools.

---

## Skills

The repo ships Claude Code skills under [`.claude/skills/`](.claude/skills/). Invoke them in Claude Code with `/<name>`:

- **`/fix-flags`** — reads the issues you 🚩-flag in the app, investigates them against the real session data, fixes them, verifies with `--selfcheck`, and marks them resolved.
- **`/tracker-gap`** — add or uplift a capability at the **shared seam** so every provider (Claude, Auggie, …) inherits it — never a forked one-off. Ships a self-check assertion and proves it end-to-end.
- **`/tracker-push`** — the maintainer's commit-and-publish workflow (green self-check → commit → push), so a change ships without leaving the tree half-committed.

---

## Good to know

- **Restart to see UI/parse changes.** The page and parsers are loaded at startup; only `flags.json` / `titles.json` are read live. After editing `aitracker/` or `web/`, run `make serve` (or restart the process).
- **Auggie CLI** reads the full local transcript (`~/.augment/sessions/`) — summary, tokens, narration, files, commands, reads, working folder, and git branch — at near-Claude parity. The only gaps are background agents/shells (Auggie has no such model), command exit status (Auggie doesn't record it, so its commands render as ✓), and **▶ push** delivery (Auggie has no hooks — the note still queues, you deliver it with ⧉ copy).
- **Augment VS Code / Cursor extensions** are read from per-workspace IDE storage (`workspaceStorage/**/Augment.vscode-augment/`) — **todos + files-touched only**, honestly degraded. The chat transcript lives in an `augment-kv-store` LevelDB that stdlib can't decode, so the narration panel says exactly that instead of pretending it's empty. Everything the SPA does render (todos, files, source badge, live filter, search, 📝 notes, 🚩 flags, rename, pin) works for these sessions the same way it does for the other two.
- **"Live" is a 5-minute window** since the last activity. Background-agent completion is inferred from that window, so an agent-finished notification can lag a few minutes; background shells with real process state notify promptly.
- **Everything stays on your machine.** Read-only against the tool logs, no outbound network, no telemetry.

---

## Project layout

```
aitracker/                     the app package (stdlib only): providers/, web/, server, cli
web assets in aitracker/web/    index.html · app.css · app.js (inlined at serve time)
tests/                unit tests + evals — the mandatory gate
hooks/pre-commit               runs the gate before every commit (make hooks)
hooks/drain-notes.py           optional Claude Code hook: delivers ▶ pushed notes (3 events)
Makefile                       make serve / stop / check / test / hooks
docs/screenshot.png            the dashboard screenshot in this README
CLAUDE.md / AGENTS.md          context for AI agents working in this repo
.claude/rules/                 hard conventions for edits (single-file, no deps)
.claude/skills/fix-flags/      skill: fix issues you 🚩-flag in the app
.claude/skills/tracker-gap/    skill: add a capability at the shared seam
.claude/skills/tracker-push/   skill: commit + publish workflow
flags.json / titles.json / pins.json / notes.json   your local data (git-ignored)
port / token / drain.log       where the server is, a local credential for the drain hook,
                               and why a push failed — all runtime, all git-ignored
```

## Testing (mandatory)

Every change must keep the gate green — the built-in `--selfcheck` **and** the `tests/`
suite (stdlib `unittest`, no deps): granular unit tests for the helpers plus end-to-end evals that
parse a fixture session and assert the whole derived view, so a break in any feature fails here.

```bash
make check     # run both — must be green before anything lands
make hooks     # once per clone: install the pre-commit hook that runs `make check`
```

With the hook installed, a commit is **blocked** until the gate passes. Add a test alongside any new
parser branch, helper, or provider (mirror the fixtures already in `_selfcheck()` / `tests/`).

---

Made with ❤️ in Bengaluru. Developed by [Pritam](https://tinyurl.com/pritamm93).
