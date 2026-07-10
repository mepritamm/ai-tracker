# AGENTS.md

Tool-agnostic guide for AI coding agents working in this repo.

**ai-tracker** is a single-file, zero-dependency Python tool: `tracker.py` = a stdlib `http.server` backend + an embedded vanilla-JS SPA. There is no framework, no build step, and no package tree — that is deliberate. Do not split the file or add dependencies.

- **Run / test:** `make serve` (start on :8787), `make stop`. **`make check` is the mandatory gate** — it runs `python3 tracker.py --selfcheck` **and** the `test_tracker.py` suite; both must be green before any change lands. Install the enforcement once with `make hooks` (a pre-commit hook that blocks commits which fail `make check`). Add a test for any new parser branch, helper, or provider.
- **Restart to see UI changes** — the web page is baked into the server at startup; only `flags.json`/`titles.json` are read live.
- **Extend via providers** — each AI tool is one `Provider` adapter in `PROVIDERS`; land capabilities at the shared seam so every source inherits them.

Full context, architecture, and the hard rules are in **[CLAUDE.md](CLAUDE.md)** and **[.claude/rules/conventions.md](.claude/rules/conventions.md)**.
