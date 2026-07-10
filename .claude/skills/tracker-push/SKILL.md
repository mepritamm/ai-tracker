---
name: tracker-push
description: Ship ai-tracker to BOTH GitHub remotes, honoring the license-split policy. Two remotes for one working tree: `personal` (git@github-personal:mepritamm/ai-tracker.git, public MIT copy, KEEPS the LICENSE) and `advisor360` (git@github.com:advisor360/ai-tracker.git, work-org copy, must be LICENSE-FREE, enforced by a .git/hooks/pre-push hard block). advisor360 lands via a green PR (license-free branch → PR → merge); personal is a DIRECT push of `main` — no PR, because the pushing account is an Enterprise Managed User that GitHub blocks from opening/merging PRs on that repo, and personal is your own public mirror where a PR adds nothing. Flow: `make check` green, sync the README, commit on main, push main→personal, then build a LICENSE-free branch off advisor360/main and open+merge a PR there. flags.json/titles.json are gitignored and never leave. Use when asked to commit/push/ship the tracker or sync both repos. Not for editing tracker.py (that's /tracker-gap) or resolving flags (/fix-flags).
---

# Ship ai-tracker to both remotes (license-split)

Two GitHub remotes from one working tree; they must NOT be identical — the only intended difference is
the `LICENSE` file:

| Remote | Repo | LICENSE? | Lands by |
|--------|------|----------|----------|
| `personal` | `mepritamm/ai-tracker` | **keeps** LICENSE (MIT, public) | **direct push** of `main` |
| `advisor360` | `advisor360/ai-tracker` | **must be LICENSE-FREE** | **a green PR** (license-free branch) |

**Why the split flow.** The pushing account (`pmondal_a360`) is an **Enterprise Managed User** — GitHub
blocks it from opening or merging PRs on the personal `mepritamm` repo (`Unauthorized: As an Enterprise
Managed User…`). And personal is your own public mirror, so a PR there adds nothing. **advisor360 is the
work repo → it gets proper PR hygiene.** A `.git/hooks/pre-push` also hard-blocks any push to advisor360
whose commit contains `LICENSE` — a safety net; you send it a license-free branch on purpose.

- **`main`** = the LICENSE-bearing history; pushed **directly** to `personal/main`.
- **advisor360/main** advances only by **merging a license-free PR**.
- **Never** committed: `flags.json`, `titles.json` (personal data) — `.gitignore`d. Confirm before every push.
- **The README ships with the code** — see the sync gate (step 3).

## Preflight

Work from the repo root. Do commits, pushes, and merges as **separate Bash calls** (the classifier tends
to block one call that bundles them).

1. **Gate.** `make check` must be green — the built-in `--selfcheck` **and** the `test_tracker.py` suite.
   A pre-commit hook enforces it (install once with `make hooks`). Never push a red build.
2. **Data stays local.** `git status --porcelain --ignored | grep -E 'flags.json|titles.json'` — ignored (`!!`), never staged.
3. **Sync the README (a push/merge blocker).** Update `README.md` in this change whenever it adds/renames/
   removes a user-facing capability/panel/badge/flag/endpoint, changes how to install or run it, shifts
   Claude↔Auggie parity (keep the How-it-works table honest), or adds/removes a skill or top-level file
   (keep Skills & Project layout current). Read the diff: "does the README still describe this accurately?"

## Personal — direct push (with LICENSE)

4. **Commit on `main`** (never leave the tree half-committed):
   ```
   git checkout main && git pull --ff-only personal main
   git add -A                 # flags.json / titles.json stay ignored
   git commit -m "<summary>\n\n<bullets>\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
   ```
5. **Push straight to personal** — no PR (the EMU account can't open one there anyway):
   ```
   git push personal main
   ```

## advisor360 — a license-free PR

6. **Build a license-free branch off advisor360's tip, matching main minus LICENSE:**
   ```
   git fetch advisor360
   git checkout -B a360/<slug> advisor360/main
   git cherry-pick <main-commit>...              # each commit you just pushed to personal
   # ...or, if a commit touches LICENSE: git checkout main -- . ; git rm --cached LICENSE ; rm -f LICENSE
   git diff advisor360/main HEAD --name-only     # the change — must NOT include LICENSE
   git cat-file -e HEAD:LICENSE 2>/dev/null && echo "STOP: LICENSE in commit" || true
   ```
   Cherry-picking is cleanest when the commits don't touch LICENSE (they usually don't — LICENSE only
   lives on `main`). advisor360/main already equals main-minus-LICENSE, so the cherry-picks apply clean.
7. **Push the branch and open + merge the PR against advisor360/main:**
   ```
   git push advisor360 a360/<slug>:<slug>
   gh pr create --repo advisor360/ai-tracker --base main --head <slug> --title "<summary>" --body "<what/why>"
   gh pr merge --repo advisor360/ai-tracker <slug> --squash --delete-branch    # only when green
   ```
8. **Return and verify both:**
   ```
   git checkout main
   git ls-tree personal/main --name-only | grep -q LICENSE && echo "personal LICENSE ok"
   git ls-tree advisor360/main --name-only | grep -q LICENSE && echo "advisor360 LEAK" || echo "advisor360 clean"
   ```

## Handling divergence (do NOT force-push)
Edited across sessions, so a base may move.
- **personal:** `git pull --ff-only personal main` before committing; if it truly diverged, inspect
  `git log personal/main..main` and reconcile as a **superset** — the remotes differ only by LICENSE, so
  it's usually just propagating a fix. Never `git push -f` without diffing what would be lost and surfacing it.
- **advisor360:** if `advisor360/main` moved, rebuild step 6 off the new tip (`git fetch advisor360`) — the
  license-free branch bases on the tip, so its PR stays mergeable. If a feature-branch push is rejected,
  fetch and rebase the branch.

## Rules
- **advisor360 lands via a green PR; personal is a direct push** after `make check` is green. Never force-push either remote.
- **The README ships with the code** — any user-facing change updates it in the same commit; a stale README blocks the push/merge.
- `make check` green before any commit. Commit, push, and merge in **separate** Bash calls.
- The pre-push hook is the last line of defense — send advisor360 a license-free branch on purpose so it never fires.
- Commit only when asked. End messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- If the tree has a genuine architecture divergence between the remotes (not just LICENSE), STOP and surface it — reconcile as a superset, don't overwrite the side that's ahead.
