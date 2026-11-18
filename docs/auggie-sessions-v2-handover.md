# Handover — Auggie 1.3 `sessions-v2` in the session list (U1)

Written 2026-11-18 from the usage-panel session. Not started. Separate from the Usage-tab plan (`docs/usage-panel-plan.md`).

## Problem
`aitracker/providers/auggie.py` lists and parses only legacy `~/.augment/sessions/*.json` (`list_auggie` ~:319). Installed Auggie **1.3.0-prerelease** names `~/.augment/sessions-v2/` as its session dir (per the plan author's read of `/opt/homebrew/lib/node_modules/@augmentcode/auggie/auggie-v2.mjs`). Once Auggie is used again, every new session will be invisible to the tracker. That covers the list, detail, search, Agents panel and the Usage tab's Auggie cost.

## State on 2026-11-18
- `~/.augment/sessions/` newest file is Sep 16 (no Auggie use since).
- `~/.augment/sessions-v2/` holds one **empty directory** (created by a 15:07 `auggie auth status` probe). No `session.jsonl` exists anywhere under `~/.augment`.
- The v2 file shape is therefore **unknown**. Conventions rule 7 forbids writing a parser before opening a real file.

## Pointer prompt (paste into a fresh session)
```
Close the ai-tracker gap in docs/auggie-sessions-v2-handover.md via /tracker-gap.
Worktree from personal/main (or fold into the open usage-panel branch if it is still unmerged — one PR per repo).
Step 1: ask me to run one short Auggie 1.3 session (e.g. `auggie -p "say hi"`), then open the real file(s)
under ~/.augment/sessions-v2/ and record the shape (field names/types only, no content) in this handover.
Step 2: opus plan → opus adversarial review → reconcile → my sign-off, before code.
Scope: the Auggie provider reads BOTH sessions/ and sessions-v2/ through the shared list/detail shapes
(conventions rule 4), plus cost (billing/cost_usd) so the Usage tab's Auggie card stops saying "v2 not read yet".
Selfcheck assertion with a v2 fixture; make check green; /branch-sync; push the branch to personal.
```
