# Remove session: adversarial implementation review (Python side)

Reviewer: opus, 2026-11-17. Scope: `aitracker/config.py`, `.gitignore`, `aitracker/store.py`
(`load_hidden`, `set_hidden`), `aitracker/registry.py` (`all_sessions(include_hidden)`, the
`search_all` mark), `aitracker/server.py` (the `/api/list` opt-in, `POST /api/hide`),
`tests/test_cr_routes.py` (`TestRemoveSession`, `_PATHS`, `_empty_env`) and the two expected-key
edits. The review started from the assumption that the implementer's report was false. No source
or test file was edited. The probes live in `/tmp/rsreview/` and are outside the repo.

## Verdict

**No blocker. No medium.** Every claim was re-derived independently and holds. There are 3 low
findings (two of them test hygiene) and 4 informational notes that need no code change.

## Claims re-derived

| Claim | How it was checked | Result |
|---|---|---|
| Gate green | `unset TRACKER_AUTH; python -m unittest tests.test_cr_routes` gave 35 OK. `tests.test_integration` gave 122 OK. | Holds |
| T1-T4 are red when their fix is reverted | `/tmp/rsreview/probe_red.py` monkeypatches one fix away per run, with no source edit. **nofilter** (`registry.load_hidden` returns `{}`) turns T1, T2, T3' and T4 red. **listdefault** (`/api/list` goes back to `all_sessions()`) turns T1 and T3' red. **defaultfalse** turns T2 red. **noroute** (`set_hidden` is a no-op) turns T1, T3' and T4 red. With no patch, all four are green. | Holds |
| T3' is truly sticky | The test appends a timestamped line, bumps mtime to now+5 and clears `_META_CACHE`, and the session stays hidden. An `mtime <= hidden_at` predicate would bring it back, because hidden_at is about `now` and mtime is now+5. | Holds |
| `/api/hide` inherits CSRF, auth and read-only | The route is at `server.py:895`, after the `do_POST` prologue at `:662-670` (origin, `/login`, `_authok`, `_readonly`, then the body). `/tmp/rsreview/probe_ro.py` reuses `tests.test_tunnel_readonly._RO`. A proxied caller in RO mode gets **403** with `RO_ERR`, and `hidden.json` is **not created**. A local caller gets 200. | Holds |
| `set_hidden` uses the locked `_update_json` | `store.py:68-78` calls `_update_json(config.HIDDEN_FILE, mutate)` (`store.py:373`, flock on `path + ".lock"`). A no-op un-hide returns `False`, so nothing is rewritten. | Holds |
| The store import is on one line for the bundle | `registry.py:11` and `server.py:16` are each a single line. `make bundle` then `py_compile dist/tracker.py` compiles. `load_hidden`, `set_hidden`, `HIDDEN_FILE` and `"/api/hide"` are all in dist, and `config.HIDDEN_FILE` is rewritten to the bare `HIDDEN_FILE`, like `PINS_FILE`. | Holds |
| Only `/api/list` passes `False` | Grep of `all_sessions(`. The only non-test `False` is `server.py:483`. `registry.py:164` (`newest_models`), `agent_cli.py:364` and `term_vt.py:4106` keep the default. Every test caller uses the default, except T2. | Holds |
| A corrupt `hidden.json` does not crash anything | `/tmp/rsreview/probe_corrupt.py` writes `[1,2]`, `"x"`, `{bad`, an empty file, `null`, `42` and invalid UTF-8. For each, `/api/list` and `/api/search` return 200 and the session is listed. `{"c1": null}` hides c1, which is membership semantics as designed. A hide over a list-shaped file returns 200 and rewrites the file as a dict (`_update_json:397`). | Holds |
| Session-id validation | `""`, `None`, `["c2"]` and `{"a":1}` each return 400. Prefixed ids such as `auggie:zz` are accepted, which is correct: list and search ids carry the same prefix (`auggie.py:939`, `augment_ext.py:353/378`), and T2 covers `auggie:`. | Holds (see L1) |
| Gitignore | `git check-ignore -v` matches `aitracker/hidden.json` (`.gitignore:6`), `hidden.json.lock` (`:7`) and `dist/hidden.json` (`:36`). The worktree has no stray `aitracker/hidden.json*`, so the harness never wrote the real file. | Holds |
| Search mark spans every provider | The mark is set in `search_all` after the merge (`registry.py:416-418`). `test_integration` `TestSearchAllRanking` checks the key set for claude, auggie and augment-vscode. | Holds |

## Findings

### L1 (low): `/api/hide` stores an id of any length, and ids that do not exist

**Defect.** `server.py:897-900` checks only `isinstance(sid, str) and sid`.

**Repro.** POST `{"session": "x"*100000, "hidden": true}` returns 200, and the 100 KB key is written into `hidden.json`. That file is then parsed on every 2-5 s `/api/list` poll and on every search. Repeated calls grow it without bound. The caller must already be local or authenticated and not read-only, so this is self-harm or a buggy client, not an attack. `/api/pin` has the same gap. `/api/title` caps the title at 120 characters.

**Fix direction.** Reject absurd ids with 400. Keep accepting ids that are not currently listed: a Restore must work for an id that has already left the list, and a hide of a not-yet-listed id is harmless. Do **not** add an existence check through `parse_any`, which would cost a provider scan per POST.

**Way.** In the `/api/hide` block:
```python
if not isinstance(sid, str) or not sid or len(sid) > 512:
    return self._json({"error": "session required"}, 400)
```
Real ids are at most about 60 characters: a UUID plus an `augment-cursor:` prefix.

**Test.** In T1, add `self.assertEqual(self._post("/api/hide", {"session": "x"*600, "hidden": True})[0], 400)`. It is red before the fix (it returns 200).

### L2 (low): the read-only POST matrix does not list `/api/hide`

**Defect.** The `tests/test_tunnel_readonly.py:29-45` `POST_ROUTES` comment says "Every mutating route", but it does not list `/api/hide`. `_STATE` (`:25`) does not repoint `HIDDEN_FILE` either. Today `/api/hide` is protected **only by construction**, because the deny-all gate runs first (proven by `probe_ro.py`). No committed test would catch a later refactor that moves the route, or a parallel `EXTRA_POST` registration, above `_readonly()`. The matrix already misses some older routes, such as `/api/pending/run`, so this is consistency, not a regression.

**Fix direction.** Add the route to the matrix and the file to `_STATE`, so `test_every_post_is_403_and_nothing_written` also asserts that `hidden.json` is never written. Change no server code.

**Way.** In `tests/test_tunnel_readonly.py`, add `"HIDDEN_FILE"` to `_STATE`, and add `("/api/hide", {"session": "s1", "hidden": True}),` after the `/api/pin` row.

**Test.** That test is the proof. To prove it red, temporarily move the `/api/hide` block above the `if self._readonly():` line at `server.py:669`: the subTest then gets 400 or 200 instead of 403, and `HIDDEN_FILE must not be written` fails. Then revert.

### L3 (low, test hygiene): unclosed file handles in `TestRemoveSession`

**Defect.** `tests/test_cr_routes.py:805` and `:810` call `json.load(open(config.HIDDEN_FILE))`. `:817` calls `json.dump({...}, open(config.HIDDEN_FILE, "w"))`. Each one emits a ResourceWarning, which was seen in the probes. T2's write depends on CPython's refcount closing, and so flushing, the anonymous handle before `all_sessions()` reads the file. It passes today, but the result depends on the interpreter.

**Fix direction.** Use context managers. The assertions stay the same.

**Way.**
- At `:817`, use `with open(config.HIDDEN_FILE, "w") as fh: json.dump({...}, fh)`.
- At `:805` and `:810`, use a small `_read_hidden()` helper that opens the file with `with`.

**Test.** None is needed. The behaviour does not change, and `python -W error::ResourceWarning -m unittest tests.test_cr_routes.TestRemoveSession` is the check.

## Informational notes (no change)

- **I1. Fork lineage and representative ids.** The hidden filter runs before the fork loops (`registry.py:36-39` comes before `:66-91`), so these two cases can occur:
  - If parent P is hidden, a visible child C still carries `continued_from = P`, because `fork_parent_of` reads `forks.json` and not `out`.
  - If child C is hidden, P still gets `continued_as = C`.

  Both banner links open detail through `parse_any`, which ignores `hidden.json`, so nothing breaks. No client code collapses rows by lineage: the board JS reads `continued_*` only in comments, and `ext_cr_detail.js:2575-2592` only draws a banner.

  A board group tile has the id `group:<g>` (`ext_cr_board.js:2679`) and has no remove button (R8). Sessions-view agent-bucket rows and `sessionTile` pass the real `s.id`. The "representative = newest run" ids exist only in `child_agent_sessions` (the detail panel), which has no remove button. **No grouped row ever hides an id other than the one clicked.**

  Behaviour to state in the PR: hiding is **per id**. A tracker resume that forks P into a new id C makes C appear (it is not hidden), while P stays hidden.
- **I2. Non-dict JSON body.** POST `/api/hide` with body `[]` raises `AttributeError: 'list' object has no attribute 'get'`, and the connection drops with no response. **This is the same as base for every POST route:** `do_POST` does `body = json.loads(...)` and then every route calls `body.get`. It is out of scope for this PR. A future one-line guard after `server.py:675` would be `if not isinstance(body, dict): return self._json({"error": "bad body"}, 400)`.
- **I3. `hidden` is read with `bool()`.** `{"hidden": "false"}` hides, and an omitted `hidden` un-hides. The only client sends JSON booleans, so this matches `/api/pin`'s `body.get("pinned")`. No change.
- **I4. No garbage collection.** Ids whose transcripts were deleted stay in `hidden.json` forever. They are tiny and harmless, the same as `pins.json`. If it ever matters, document it as a gap. No change.
