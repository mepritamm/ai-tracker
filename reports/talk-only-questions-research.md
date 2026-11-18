# AskUserQuestion — how the Claude Code CLI renders it (research for the tracker pager)

_Opus researcher, 2026-11-18. Sources: official docs, GitHub issues, read-only greps of the local native binary `~/.local/share/claude/versions/2.1.327` (also 2.1.323/.325/.326). Bundle evidence is minified implementation, not documentation._

## 1. Layout (tab row)
- Bundle (2.1.327, tab-row component): `← ☐ Header1  ☒ Header2  ✔ Submit →`. Chip mark = `checkboxOn "☒"` (answered) / `checkboxOff "☐"` (Windows `[×]`/`[ ]`); label = `displayHeader || \`Q${i+1}\``; current chip gets the `permission` background colour. Header widths are budgeted to terminal columns (truncated).
- `←` is `inactive` (dim) on index 0; `→` dim on the Submit tab. Arrows and the Submit tab are hidden when there is exactly one non-multiSelect question (`hideSubmitTab = qs.length===1 && !qs[0].multiSelect`).
- Accessible variant: `Questions: H1 (answered), H2`.
- Third-party capture: `← ☒ Device ☐ Symptoms ✔ Submit →` — https://github.com/devswha/ovis/issues/2465
- Docs: `header` = "Short label for the question (max 12 characters)" — https://code.claude.com/docs/en/agent-sdk/user-input (bundle `max 12`).

## 2. Keys
- Bindings: `{context:"Tabs", tab:"tabs:next", "shift+tab":"tabs:previous", right:"tabs:next", left:"tabs:previous"}`.
- **Clamps, never wraps**: `prev-question → Math.max(0, i-1)`; next stops at the Submit tab (or the last question when Submit is hidden).
- Picking a single-select option auto-advances to the next tab; multiSelect shows a `Next` button (`Submit` on the last question when no Submit tab).
- ↑/↓ move between options; Enter selects; Esc cancels (transcript then says "Declined to answer Claude's questions:").
- Footer: `Enter to select · Tab/Arrow keys to navigate · Esc to cancel`.
- Number-key selection: **unverified** for the CLI (issue #107513 mentions `1`/Enter, but for VS Code).

## 3. Review / Submit, Other, multiSelect
- Bundle: title `Review your answers`; warning `Some questions are unanswered` when incomplete; lists only answered questions as the question text followed by a green `→ answer`; confirm `Submit answers` / `Cancel`. (2.1.323 also had "Ready to submit your answers?"; gone in 2.1.327 — https://github.com/herdrdev/herdr/issues/4668.)
- "Other": an automatic free-text row (`__other__`, placeholder "Type something…"); a single-select question may also get "Chat about this".
- multiSelect rows: `[✔]` / `[ ]`; answers are an array or a `", "`-joined string.
- VS Code differs: Submit is disabled until all tabs are answered (#81790, #107513); the CLI allows submitting with the warning (inferred from the bundle).

## 4. An answered prompt afterwards
- Transcript UI: `⏺ Answered Claude's questions:` then dim lines `· <question> → <answer>`. Variants: `Declined to answer Claude's questions:` (lists `· question (opt1, opt2…)`), `Claude asked:`.
- Tool result text sent to Claude: `Your questions have been answered: "Q"="A". You can now continue with these answers in mind.`

## 5. Limits
- 1–4 questions, 2–4 options each (docs and bundle `.min(1).max(4)` / `.min(2).max(4)`); header ≤ 12 chars.
- 2.1.327 also has an optional top heading and a question `kind` ("choice"/"text"), possibly gated; older transcripts lack them.

## Implications for the tracker pager (read-only)
- Imitate the tab row `← ☐/☒ header … →`, with ☒ answered / ☐ unanswered, a `Q{n}` fallback for an empty header, and the current chip highlighted.
- ←/→ clamp at the ends (no wrap); dim ← on the first chip and → on the last.
- Show no tab row or arrows for a single non-multiSelect question (matches the CLI).
- Optional last page: a read-only "Review your answers" view (question text, then green `→ answer`, answered ones only, plus "Some questions are unanswered" when that applies).
- **Never** render live Submit/Cancel buttons or an "Other" input. The tracker never answers; it shows the chosen value as text.
- For a finished prompt, mirror `Answered Claude's questions:` / `· Q → A`, or `Declined to answer Claude's questions:` for a deny.
- Handle multiSelect answers as an array or a joined string; an "Other" answer is the typed text itself.
- Expect ≤4 questions, 2–4 options and ≤12-char headers; don't hard-fail on a missing header, a heading or `kind`.

Sources: https://code.claude.com/docs/en/agent-sdk/user-input · https://github.com/devswha/ovis/issues/2465 · https://github.com/herdrdev/herdr/issues/4668 · https://github.com/anthropics/claude-code/issues/107513 · https://github.com/anthropics/claude-code/issues/81790 · local bundle 2.1.327 (+2.1.323 for the version difference).
