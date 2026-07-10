# AI Session Tracker

A zero-dependency, local web dashboard that shows you **what your AI coding sessions are doing — live**, across tools. It reads the session logs each AI coding tool already writes to disk and turns them into one readable view: a plain-language summary, todos, files touched, commands run, background agents/shells, and the assistant's own narration — refreshing every 2 seconds.

Works across tools via a small **provider** for each. Built in today: **Claude Code** and **Auggie / Augment**. Adding another is a ~2-function adapter (see [Adding a tool](#adding-a-tool)).

Nothing is sent anywhere. It's a single Python file using only the standard library, serving a local page you open in your browser.

<p align="center">
  <img src="docs/screenshot.png" alt="Claude Code Session Tracker — live dashboard showing the session sidebar, a plain-language summary, background agents, and Claude's narration" width="880">
</p>

<p align="center"><sub>Live dashboard — session sidebar, summary (Goal / Now / So far), stat chips, background agents & shells, and Claude's own narration.</sub></p>

---

## Quick start

Requires **Python 3.8+** (standard library only — no `pip install`).

```bash
python3 tracker.py
```

That's it. It starts a local server on **http://localhost:8787** and opens your browser. Pick a session from the sidebar (or paste a session id) and watch it work.

Or use the Makefile, which cleanly restarts (frees a stuck port so UI updates always take effect):

```bash
make serve            # start (or restart) the tracker
make stop             # stop it
make serve PORT=9000  # use a different port
make check            # run the built-in self-check
```

Other flags: `python3 tracker.py --version | --help`.

---

## What it shows

**Sidebar** — every session across all your projects, newest first, with a source badge (Claude Desktop / Claude CLI / Claude VS Code / Auggie), a live dot, and a short title.
- **Click "N live"** to filter to only active sessions.
- **Search** by keyword — matches your prompts and the conversation; sessions whose *name* matches rank first.
- **✎ rename** any session to a title that means something to you.

**Main view** for the selected session:
- **Session summary** — Goal, what it's doing *Now*, and a one-line "So far".
- **Background agents & shells** — running ones shown; finished ones one click away. Toasts + a sound when one completes.
- **Narration** — Claude's own words, step by step (full markdown rendering in the modal).
- **Todos**, **Files** (with a Diff ⇄ Rendered-markdown toggle), **Commands** (with ✓/✗), and **Requests**.
- **🚩 Flag** anything you want to fix later — see the [fix-flags skill](#the-fix-flags-skill).

---

## How it works

Claude Code writes an append-only log for every session at `~/.claude/projects/<project>/<session-id>.jsonl`. Background agents write to a `<session-id>/` subdirectory. The tracker:

1. **Serves** a single HTML page (`GET /`).
2. **Parses** a session's log on demand (`/api/session`) into the structured view.
3. The browser **polls** every 2s — that re-read is the "live".

Because it only reads what's already on disk, there's no integration, no API key, and no network traffic.

Each AI tool plugs in as a **provider** (a small adapter). The registry (`PROVIDERS` in `tracker.py`) merges every available provider's sessions into one list and routes each session id — namespaced by prefix — to the adapter that owns it. One broken provider can't sink the list.

---

## Supported tools

| Tool | Source on disk | Status |
|------|----------------|--------|
| **Claude Code** (Desktop / CLI / VS Code) | `~/.claude/projects/**/*.jsonl` | ✅ built in |
| **Auggie / Augment** | `~/.augment/sessions/*.json` | ✅ built in |
| Cursor, OpenAI Codex | SQLite databases | ⚙️ needs an adapter (format-specific reader) |
| GitHub Copilot CLI | binary LMDB blobs | ⚙️ needs an adapter |

Only tools that keep a **readable local transcript** can be adapted. Claude and Auggie write plain JSON/JSONL; others use SQLite or binary stores that each need their own reader.

## Adding a tool

Write one `Provider` in `tracker.py` and register it — no core changes:

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

## The fix-flags skill

Included at [`.claude/skills/fix-flags/`](.claude/skills/fix-flags/) — a Claude Code skill that reads the issues you 🚩-flag in the app, investigates them against the real session data, fixes them, verifies with `--selfcheck`, and marks them resolved. Invoke it in Claude Code with `/fix-flags`.

---

## Good to know

- **Restart to see UI changes.** The page is served fresh on startup, so after editing `tracker.py` you must restart the server (`make serve`). Your data files (`flags.json`, `titles.json`) are read live and don't need a restart.
- **Auggie / Augment sessions** show up too, but Augment keeps the full transcript in its cloud — so only the local task list and activity time are available for those.
- **Background-agent completion** is inferred from a 5-minute inactivity window, so an agent-finished notification can lag a few minutes behind the actual finish. Background shells with real process state notify promptly.

---

## Project layout

```
tracker.py                     the entire app (stdlib only)
Makefile                       make serve / make stop / make check
.claude/skills/fix-flags/      Claude Code skill to fix flagged issues
flags.json / titles.json       your local data (git-ignored)
```

---

Made with ❤️ in Bengaluru. Developed by [Pritam](https://tinyurl.com/pritamm93).
