# Claude Code Session Tracker

A zero-dependency, local web dashboard that shows you **what your Claude Code sessions are doing — live**. It reads the session logs Claude Code already writes to disk and turns them into a readable view: a plain-language summary, todos, files touched, commands run, background agents/shells, and Claude's own narration — refreshing every 2 seconds.

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
