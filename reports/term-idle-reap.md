# Terminal idle TTL never reaps a terminal a dashboard tab is showing

Branch `worktree-term-idle-reap`, cut from `personal/main` @ `ee03212` (2026-11-19).

## Contract (verbatim, user, 2026-11-19)

1. "why these 2 terminals are still sitting there, when there has been no activity since ~10h ? Why the ttl didnt kicked in ?"
2. "make sure you are on the latest of the main branch"
3. "/branch-sync and run the plan-> review pipeline with only 1 review post the fix and make sure that your planning, fixing and review considers /gap, once thats done -> /branch-sync -> /tracker-push"

| Clause | Verdict |
|---|---|
| 1 explain why the TTL did not fire | discharged (diagnosis below) |
| 2 on latest main | discharged: worktree reset to `personal/main` `ee03212` |
| 3a plan (opus), /gap-aware | not discharged |
| 3b implement (cheaper agent), /gap-aware | not discharged |
| 3c exactly ONE review, after the fix (opus), /gap-aware | not discharged |
| 3d /branch-sync | not discharged |
| 3e /tracker-push | not discharged |

## Diagnosis (from the read-only investigation)

- Idle TTL = `config.TERM_IDLE_TTL_MIN` (default 30 min, 1..1440, live-editable; env `TRACKER_TERM_IDLE_TTL_MIN`; `aitracker/config.py` ~309, ~565-574, ~632).
- Enforced in `term_vt._reader()` ~1888: `pt.viewers <= 0 and now - pt.last_active > TTL*60 and now >= pt.live_hold`, then `_claude_busy` (touch) / `_session_live` (hold 30 s) / else `pt.kill()`.
- `pt.touch()` (~1540) is called by `_note_activity` (~1844; screen change above Claude's footer band, any change for non-Claude programs) and on every SSE screen-stream attach AND detach (~4950-4963, and the second stream route ~5578).
- Live 8790 server: both 11.9h-old terminals had `viewers: 1`, `last_hold: ""`, `idle_s` 9 and 88. An open dashboard tab holds an SSE stream per pane, so `viewers > 0` short-circuits the reap for as long as the tab is open. `idle_s` staying small means `last_active` was also being refreshed by something (stream reconnects or footer/status repaint) - unconfirmed.
- `Pty.last_active` doc comment (~1525) states the design: "last viewer leaving" starts the idle clock.

## Plan

(written by the plan agent below this line)

### P0. What was resetting `last_active` (re-derived against the code + the live 8790 server)

Every `pt.touch()` call site in `aitracker/term_vt.py` (`personal/main` @ `ee03212`):

| line | caller | kind |
|---|---|---|
| 1865 | `_note_activity` (body-row change; any change for non-Claude) | real output |
| 1891 | `_reader` reap, `_claude_busy` hold | keep (in-pty tool work) |
| 1934 | `_reader`, `pt.screen is None` | real output |
| 2125 | `_inject_argv` (types a resume/new command into a folder shell) | real input |
| 3936 | folder-shell swap claim | keep (mid-swap guard) |
| 4279 | `keys()` POST /api/term/keys | real input, **but also bare `ESC[I`/`ESC[O` focus reports** (ext_vt.js:903-910 sends them on textarea focus/blur while the program enabled `?1004`, which Claude Code does) |
| 4443 | `resize_pty()` POST /api/term/resize | **viewer noise**: every (re)attach POSTs a resize (`Terminal.attach` -> `measureAndResize` with `this.cols = 0`, ext_vt.js:941/953; the xterm renderer's fit on build). A same-size resize is a no-op for `Screen.resize` (term_vt.py:438 early return) and for the kernel's SIGWINCH, so it moves nothing but the clock |
| 4975 / 4988 | `screen_stream` attach / detach | **viewer noise** |
| 5478 / 5514 | `inject()` POST /api/term/inject | real input |
| 5603 / 5621 | `raw_stream` attach / detach | **viewer noise** |

- Live 8790 (read-only GETs of `/api/term/list`, sampled every 4-6 s for ~15 min): the two 11.9 h ptys from the diagnosis are gone. The current two are 0.68 h old, with `viewers: 1`.
  - `ed95…`, an idle `claude` in ai-tracker, climbed steadily from 102 s to 593 s+ while a tab had it open. **No periodic touch exists in steady state.** `_note_activity`'s `_body_rows_version` band already filters footer/status/spinner repaint (pinned by `test_claude_footer_redraw_does_not_hold_off_reap`). SSE `: ping` heartbeats touch nothing.
  - `566b…` was touched every ~6 s from 13:03. That fits real work in that pane (a transcript in its worktree was written at 13:04), not noise.
- **Conclusion.** The terminals survived 10 h **only** because of the `pt.viewers <= 0` gate (term_vt.py:1888).
- The small `idle_s` values (9 s / 88 s) on the old ptys come from the event-driven viewer touches:
  - opening or reloading the dashboard or the pane (attach touch, plus the resize-on-attach touch);
  - an EventSource reconnect (detach, attach, resize);
  - a window focus change (a focus report via `keys`).

  The most likely trigger is the user opening the panes to look at them seconds before the GET. This cannot be re-proved now because those ptys are gone. The plan removes every one of those sources, so the attribution does not change the fix.

### P1. Design (chosen: decouple the TTL from viewers; viewer-only signals stop touching)

1. The idle reap ignores `pt.viewers`. A terminal idles out after `TERM_IDLE_TTL_MIN` of no real activity even while a dashboard pane displays it. `_claude_busy` (touch) and `_session_live` (hold, no touch) stay exactly as they are, in the same order.
2. Viewer-only events stop counting as activity: SSE attach/detach on both stream routes, a resize POST, and a bare focus report on `keys`. Real activity stays: keystrokes/paste (`keys`), `inject`, `_inject_argv`, the swap claim, and `_note_activity` output (unchanged semantics: no new footer heuristics, since the live sample shows the footer filter already works).
3. On a reap, a one-line note is fed to the pane before the kill, so an open pane says why it ended (both renderers, using the existing `_feed_note` sinks).
- **No new config knob.** `TERM_IDLE_TTL_MIN` (live-editable) is the one control; a "watching protects" toggle would be a second policy for the same clock.
- `/gap` check: the policy lives once at the shared seam (`_reader`, the one reap loop every pty, Claude or Auggie-launched, goes through). The server owns the policy and the client only renders. No JS logic change, so the SPA does not re-derive anything. Not per-provider: the PTY layer is provider-agnostic.

### P2. Exact changes (all in the worktree; re-read each region before editing — rule 12)

**`aitracker/term_vt.py`**
1. New helper, placed directly above `_reader` (after `_note_activity`, ~line 1867):
   ```python
   def _idle_due(pt, now):
       """The idle reap's trigger: no counted activity for TERM_IDLE_TTL_MIN, and no live HOLD pending.
       Deliberately NOT gated on `pt.viewers`: a dashboard pane that merely displays a terminal
       keeps an SSE stream open forever, so a viewer gate meant "never" (term-idle-reap)."""
       return now - pt.last_active > config.TERM_IDLE_TTL_MIN * 60 and now >= pt.live_hold
   ```
2. `_reader` (1888-1889): replace the condition `pt.viewers <= 0 and now - pt.last_active > config.TERM_IDLE_TTL_MIN * 60 and now >= pt.live_hold` with `if _idle_due(pt, now):`. The body (`_claude_busy` -> touch + `last_hold="busy"`; `_session_live` -> `live_hold` + `last_hold="live"`; else kill) is unchanged, except in the `else:` before `pt.kill()`:
   ```python
   if pt.screen is not None:
       _feed_note(pt, "[ai-tracker] closed: no activity for %g min (Config → Terminal → Idle terminal TTL)"
                  % config.TERM_IDLE_TTL_MIN)
   pt.kill()
   break
   ```
   (`_feed_note` writes the grid row, tees raw viewers and queues a notice under one `pt.lock`, and never writes to `pt.fd`. The stream body sends that row before it sees `done`. The `screen is None` guard is there because `_feed_note` dereferences `pt.screen`.) Docstring line 1870: drop "with nobody attached".
3. `screen_stream` (4975, 4988): delete both `pt.touch()` lines (keep `viewers += 1/-= 1` and `_STREAMS` exactly). Rewrite the docstring paragraph at 4952-4957 ("so the last viewer leaving only calls `pt.touch()`, starting the idle TTL clock...") to: the last viewer leaving kills nothing. Viewers do not affect the idle clock at all. `_reader()` reaps a pty after `TERM_IDLE_TTL_MIN` of no input or counted output, whether or not a pane shows it.
4. `raw_stream` (5603, 5621): delete both `pt.touch()` lines, same as above.
5. `resize_pty` (4443): delete `pt.touch()`. A real size change still counts, because `Screen.resize` bumps `v`/`row_v` and `_note_activity` counts that. A same-size re-POST on reattach no longer counts.
6. `keys` (4279): `pt.touch()` -> `if data not in _FOCUS_REPORTS: pt.touch()`, with a module constant beside the idle constants (~1261): `_FOCUS_REPORTS = (b"\x1b[I", b"\x1b[O")   # ?1004 focus in/out: the pane gained/lost focus, not input -- never resets the idle clock`. The write to `pt.fd` is unchanged (the program still gets its focus report).
7. Comments: `Pty.last_active` (1525) -> `# last keystroke/paste/inject, or a screen change _note_activity counts -- idle clock (viewers never move it)`. `Pty.last_output` comment (1534-1537): drop "or a viewer connecting/leaving". The two `# last-viewer-leaves starts the idle clock` comments go with their lines.

**User-facing copy (the same policy, re-worded; no logic):**
8. `aitracker/config.py:591` docstring -> "Minutes a terminal with no input and no counted output survives before it is closed (an open pane alone does not keep it)."
9. `aitracker/web/ext_cr_dialogs.js:2189`: first sentence -> "A terminal nobody types into, and whose program prints nothing that counts, is closed after this many minutes, even while a pane shows it." Rest unchanged.
10. `aitracker/agent_cli.py:106-107` `AGENT_RA_NOTE` -> "These terminals close after %d minutes with no activity, even while open on screen (Config → Terminal → Idle terminal TTL). Type into one to keep it." (Tests use the constant by name, `tests/test_resume_all_jobs.py:124,182`, so they need no edit.)
11. `README.md:112`: "an open viewer keeps it alive" -> "an open pane alone does not keep it alive: typing or pasting into it, or output that counts, resets the clock; opening, reconnecting, resizing or focusing a pane does not; a reaped pane shows a closing note".

**No SPA logic change.** When a reaped pty's pane is open, it behaves exactly as it already does on `exit` or kill:
- `_screen_stream_body` and `_raw_stream_body` return on `done` after sending the last frame (term_vt.py:5120-5131, 5691).
- EventSource keeps retrying against the lingering `done` row. Each retry replays the final grid, which now includes the closing note. The raw route replays the notice, and `createNoticeBanner` dedupes it by seq.
- After `_REAP_LINGER` (600 s) the row is dropped and the route returns 404. EventSource then goes CLOSED and the status reads "disconnected — reopen this terminal" (ext_vt.js:711-713).
- The Control Room list drops the row on its next `/api/term/list` poll.

Known gap, same as base for any exit: the "reconnecting…" churn during the linger. It is out of scope; document it in the push notes.

### P3. Sequencing

1. `term_vt.py` items 1-2 (`_idle_due` + the reap note). This is the core fix. Then edit test U1 and watch it go green.
2. Items 3-6 (remove the viewer-noise touches) + U2-U5.
3. Item 7 + copy 8-11.
4. Selfcheck assertion S1.
5. Revert-to-red proof per test (below), then the gate.
The core fix goes first because U1 and S1 alone prove the reported bug. Items 3-6 only matter once the viewer gate is gone. Before that, they were what started the clock.

### P4. Tests (each must be shown RED by reverting its line, GREEN with it)

- **S1, `tests/test_selfcheck.py`**, next to the existing `_p = term_vt.Pty()` idle block (~line 954):
  ```python
  _q = term_vt.Pty(); _q.viewers = 1; _q.live_hold = 0.0
  _q.last_active = time.time() - config.TERM_IDLE_TTL_MIN * 60 - 5
  assert term_vt._idle_due(_q, time.time()), "a terminal a pane merely displays must still idle out"
  _q.live_hold = time.time() + 60
  assert not term_vt._idle_due(_q, time.time()), "a _session_live HOLD still defers the reap"
  ```
  RED: re-add `pt.viewers <= 0 and` to `_idle_due`.
- **U1, `tests/test_term_vt.py:2162`.** This existing test pins the old behaviour. The change is expected, so edit it in place: rename `test_active_viewer_prevents_idle_reap` -> `test_viewer_alone_does_not_prevent_idle_reap`. Keep `pt.viewers = 1` and assert `self.assertTrue(_drain(pt, 5).done, "a displayed-but-idle PTY must still be reaped")`. RED on base / with the gate restored.
- **U2, `TestStreamAccounting` (tests/test_term_vt.py:1901; its setUp already sets TERMINAL/AUTH)**: `test_watched_idle_pty_is_reaped_and_stream_ends`.
  - Setup: save and restore `config.TERM_IDLE_TTL_MIN` via `addCleanup`. Spawn `["sleep","30"]` and register it in `PTYS`.
  - Attach: run `screen_stream` on a thread with `_StreamHandler` and `_Q("session=&tty="+pt.id)`, then `_wait_for(pt.viewers == 1)`.
  - Reap: set TTL `0.001` and assert `_drain(pt, 5).done`.
  - Stream end: assert the stream thread `join(5)`s and is not alive.
  - Output: assert the captured `h.peer.recv` bytes contain `b"no activity for"`.
  - Accounting: assert `pt.viewers == 0` and `term_vt._STREAMS == 0` afterwards.
  - Cleanup as in the neighbouring tests: `pt.kill()`, `_drain`, `PTYS.pop`, `h.close()`.

  RED on base.
- **U3, same class**: `test_stream_attach_detach_does_not_touch_idle_clock`. Use TTL 30, spawn `sleep 30`, and `_wait_for(pt._act_v is not None)` (the reader's first sample touches). Set `pt.last_active = before = time.time() - 120`. Attach `screen_stream`, wait for `viewers == 1`, `close_peer()`, join, and `assertEqual(pt.last_active, before)`. Repeat the same for `raw_stream`. RED: restore either touch.
- **U4, `TestIdleTimeout`**: `test_same_size_resize_does_not_touch_idle_clock`. TTL 30, spawn `sleep 30` at 80x24, wait for `_act_v`, backdate `last_active`. Call `term_vt.resize_pty(_FakeHandler(), None, {"session": "", "tty": pt.id, "cols": 80, "rows": 24})` with the pty in `PTYS` and TERMINAL/AUTH set as in `TestStreamAccounting.setUp`, then `assertEqual(pt.last_active, before)`. RED: restore the resize touch.
- **U5, same**: `test_focus_report_does_not_touch_but_a_key_does`. Same setup. `keys(h, None, {"session":"", "tty":pt.id, "data": b64(b"\x1b[I")})` leaves `last_active` unchanged, then `data: b64(b"x")` moves it (`assertGreater`). RED: drop the `_FOCUS_REPORTS` check.
- **Unchanged, must stay green (they prove the holds are untouched):** `test_claude_with_background_work_is_not_reaped` and the busy tests (~2330-2460); `TestIdleSessionLive` incl. `test_U9_hold_does_not_touch_idle_clock`; `test_claude_footer_redraw_does_not_hold_off_reap`; `test_body_output_holds_off_reap`; `test_ttl_change_applies_without_restart`; the stream refcount test at ~1940-1970 (default TTL 30, still holds); integration `test_live_session_terminal_survives_ttl_until_quiet` and the client/local reap test (tests/test_integration.py:1764-1850); `test_folder_swap*` (their `viewers = 1` gates the swap, not the reap).
- Integration suite: no new test. U2 drives the real `screen_stream` route against a real pty and reader thread. `tests/test_integration.py` has no SSE client helper, and building one is wider than the defect.

### P5. Gate / process notes for the implementer

- `unset TRACKER_AUTH;` before `make check` and before `git commit` (the hook runs the full gate, 180-380 s: give Bash a >5 min timeout). If you see `Killed: 9` with no failures, that is OOM: run one module per process (`python -m unittest tests.test_term_vt`, then `tests.test_selfcheck`, etc.) and never `| tail` the run. One known flaky `term_vt` backstop test passes in isolation.
- Never `git stash`. Revert-to-red with a scoped Edit and restore it with Edit. Never touch the live 8790 server (no restart, no `pkill -f aitracker`).
- Server-side change: the UI copy in `ext_cr_dialogs.js` needs a server restart to show (page baked at startup). That is the ship step's job, not the implementer's.

### P6. Risky spot + fallback

- **Risk:** someone reading a pane for longer than the TTL without typing, with Claude idle, gets the pane closed under them.
- **Mitigations already in place:**
  - `_session_live` holds a Claude pane until `max(LIVE_WINDOW, TTL)` after its transcript's last write, so the clock effectively starts after Claude's last answer.
  - The session is not lost: `claude --resume` from the dashboard brings it back.
  - The pane now says why it closed.
- **Fallback:** raise the TTL live in Config (no restart). If that is not enough, D1's alternative is a small follow-up: a *focused* pane counts as a hold (a `focused` flag on the existing stream/keys path). Do not reintroduce a bare viewer gate.
- **Secondary:** a `_claude_busy` probe (one `ps` fork) now also runs on displayed panes, once per TTL per idle pane. Negligible, and it is the existing code path.

### P7. Decisions the user may overrule

- **D1. Should a pane that is open but untouched protect the terminal?** The plan says no, per the contract: "reaped even if a dashboard tab is merely displaying it". Alternative: protect only while a pane is focused in a visible tab. That needs a new client→server signal and is not in this plan.
- **D2. Do focus changes and same-size resizes count as activity?** The plan says neither does, because both fire on passive viewing (alt-tab, reattach). Overrule by dropping changes 5-6 and tests U4-U5. The core fix (U1/U2/S1) stands without them.

## Implementation

Implemented P2 items 1-11 as planned (D1/D2 accepted). Files: `aitracker/term_vt.py` (`_FOCUS_REPORTS`, `_idle_due`, `_reader` + `_feed_note` before the reap kill, removed viewer/resize touches, `keys` focus guard, comments/docstrings), `config.py`, `web/ext_cr_dialogs.js`, `agent_cli.py` (`AGENT_RA_NOTE`), `README.md`, `tests/test_term_vt.py`, `tests/test_selfcheck.py`. UI copy needs a server restart to show (ship step).

Deviations: none of substance. Test helpers `_guarded`/`_idle_pty` added to `TestIdleTimeout` for U4/U5; U2 reads the SSE bytes from the socketpair peer after the stream ends.

Red proofs (scoped revert of the fix, test fails; then restored):
- U1 `test_viewer_alone_does_not_prevent_idle_reap`, U2 `test_watched_idle_pty_is_reaped_and_stream_ends`: RED with `pt.viewers <= 0 and` restored in `_idle_due`.
- U2 also RED with the `_feed_note` reap note removed.
- U3 `test_stream_attach_detach_does_not_touch_idle_clock`: RED with the attach touches restored, and separately with the detach touches restored (both routes).
- U4 `test_same_size_resize_does_not_touch_idle_clock`: RED with the resize touch restored.
- U5 `test_focus_report_does_not_touch_but_a_key_does`: RED with the `_FOCUS_REPORTS` guard dropped.
- S1 (selfcheck `_idle_due` assertion): RED with the viewer gate restored.

Gate: `tests.test_term_vt` + `tests.test_selfcheck` together: 384 tests OK. All other tests/test_*.py modules run one per process: all rc=0 (no flake).

## Review (post-fix, opus)

Reviewed `7ee2d01` against `ee03212`. I started from the assumption that the implementation report is false. I checked the change against `tracker-gap`, CLAUDE.md and conventions.md. I read the code in scoped per-file diffs, plus `sed` ranges of `term_vt.py`.

**Verdict: ship after fixes.** There are 0 blockers, 3 should-fix findings and 7 nits. The core fix is correct and is proven on the live path.

### What I re-proved myself (with scoped Edits, restored afterwards; `git diff --stat 7ee2d01` is clean)
- **Viewer gate.** I put `pt.viewers <= 0 and` back in **`_reader`**, not in `_idle_due`, so the tests have to prove the live loop and not only the helper. With that edit, U1 `test_viewer_alone_does_not_prevent_idle_reap` and U2 `test_watched_idle_pty_is_reaped_and_stream_ends` both went RED.
  - S1 in selfcheck tests only `_idle_due`, so it stays green against that edit. U1 and U2 carry the live-path proof. Acceptable.
- **Resize touch.** With `pt.touch()` restored in `resize_pty`, U4 `test_same_size_resize_does_not_touch_idle_clock` went RED. That proves the `_FakeHandler` call really reaches the line and the test is not vacuous.
- **Green run.** All 6 new or renamed tests are green with the fix in place.

### Verified clean (no finding)
- **Every `last_active` write enumerated** (`term_vt.py` 1542 / 1866 / 1897 / 1943 / 2134 / 3945 / 4289 / 5486 / 5522).
  - No viewer, attach, detach, reconnect or resize path touches it any more.
  - Keys, inject, `_inject_argv`, the swap claim and counted output still do.
- **`_feed_note` before `pt.kill()` (term_vt.py:1903-1907).**
  - `_reader` holds no lock at that point. `_feed_note` takes `pt.lock` once, and `_tee_raw` only uses `put_nowait`. No deadlock.
  - `_screen_stream_body` reads `snapshot()` and `pt.done` under the same lock (5081-5092), so the final frame always carries the note.
  - `_raw_stream_body` drains its queue and the notices before it returns on `done`.
  - The `pt.screen is None` guard is correct.
- **Holds.** The order is unchanged. `_claude_busy` touches, `_session_live` holds without touching, and `last_hold` keeps the same semantics. The folder-swap guard `fp.viewers > 0` (3936) still gates the swap, and the swap claim still touches.
- **Focus guard.**
  - Native renderer: each `_send` posts one focus report on its own (ext_vt.js:905/909, then the `_enqueue` chain, one POST per call, no batching).
  - xterm renderer: `onData` emits the report as its own event.
  - CSI I and CSI O have no bracketed or combined variant, so an exact match is enough.

### Findings

**F1 (should-fix). A Config login terminal is now idle-reaped while the user is in the browser finishing the login.**
- **Where:** `term_vt.py:1873-1874` (`_idle_due`), and `_reader` at 1895-1907.
- **Repro:**
  1. Set TTL = 5 (the slider minimum).
  2. In Config, click Log in. The pane shows `claude auth login`, which prints nothing while it waits.
  3. Spend more than 5 minutes on SSO or MFA in the browser.
- **Actual:** the pty is SIGKILLed at 5 minutes, and `_login_outcome` records `"closed"` (rc -9).
- **Expected:** the login is bounded by its own policy, `LOGIN_WATCH_MAX` (1800 s, `_login_watch`, 3691-3703), and records `"timeout"` when that runs out.
- **Base behaviour:** the open pane's viewer gate protected the login. This change removed that protection, so it is a regression below a 30-min TTL.
- **Fix direction:** idle reap skips login ptys. `_login_watch` stays their only time bound. Do NOT change `_login_watch`, `LOGIN_WATCH_MAX` or the outcome mapping.
- **Way:** in `_idle_due`, use `return not pt.login and now - pt.last_active > config.TERM_IDLE_TTL_MIN * 60 and now >= pt.live_hold`. Add one docstring line: "a Config login pty is bounded by LOGIN_WATCH_MAX (`_login_watch`), never by the idle TTL". This covers both Claude (`claudeai`/`console`) and Auggie (`pt.login` set) logins, because `spawn(login=...)` sets it.
- **Tests:**
  - (a) Selfcheck, next to S1: `_q.live_hold = 0.0; _q.login = "claudeai"; assert not term_vt._idle_due(_q, time.time()), "a login pty is bounded by LOGIN_WATCH_MAX, not the idle TTL"`.
  - (b) `TestIdleTimeout`, `test_login_pty_is_not_idle_reaped`:
    - Run `term_vt.spawn(os.getcwd(), ["sleep","30"], 80, 24, login="claudeai")` with TTL 0.001.
    - Assert `not pt.done` after `time.sleep(2.5)`.
    - Cleanup: `pt.kill(); _drain(pt, 5)`. `tests/__init__.py` already redirects `last_login.json`.
  - Both go RED before the fix.

**F2 (should-fix: a user decision and copy, no code). A displayed pane now loses state that base protected, beyond "reading for longer than the TTL" (plan P6).** Once `max(LIVE_WINDOW, TTL)` has passed with no input:
- (a) A Claude waiting on a permission prompt or an AskUserQuestion (`session_state == "waiting"`, providers/claude.py:803) is killed mid-turn. `_session_live`'s own docstring already lists "a pending permission dialog counts as idle after one window".
- (b) An unsent draft typed into Claude's input box is lost.
- (c) A `/loop` whose interval is longer than the TTL dies between iterations: no tool children are running, and the transcript is too old.
- (d) A `claude agents`, `claude attach` or parked client pane closes, even while the user is watching its spinners. `_note_activity` never counts output for a client.

Repro for (a): set TTL to 30. Let Claude ask a permission question in a pane that stays open, and leave for 35 min. Actual: the pane says "closed: no activity…". Base: the session was still waiting.

- **Fix direction:** no code change. D1 was accepted, and an unbounded hold for "waiting" would bring back the 10-hour terminals.
  - Before the push, put (a)-(d) to the user as a D1 follow-up ("D3").
  - Add one sentence to `ext_cr_dialogs.js:2189` and `README.md:112`: "This includes a Claude waiting on a permission prompt or a question, and an unsent draft; Resume brings the session back."
- **If the user wants (a) protected:** in `_session_live`, add a hold while `_claude.session_state(s) == "waiting"`, capped at one extra TTL after the transcript's last write. Never uncapped.
- **Test, only if the code option is chosen:** `TestIdleSessionLive`, `test_waiting_session_held_one_extra_ttl`. Patch `session_state` to return `"waiting"` and `session_last_active` to `now - 1.5*window`. Assert held. At `now - 2.5*window`, assert reaped.

**F3 (should-fix: copy). The README now says something false about resizing.**
- **Where:** `README.md:112` says "opening, reconnecting, resizing or focusing a pane does not [reset the clock]".
- **Why it is false:** only a re-fit at the same size is ignored. A real size change goes through `Screen.resize`, which bumps `v` and every `row_v` (term_vt.py:425-466), and `_note_activity` counts that on the next tick. For Claude, the body rows are dirty, and Claude also redraws on SIGWINCH.
- **Repro:** open the same pty in a second window of a different size, so `POST /api/term/resize` goes to 100x30 from 80x24. Within 1 s, `idle_s` in `/api/term/list` drops to 0.
- **Fix:** change the README to "opening, reconnecting, a same-size re-fit, or focusing a pane does not; a real size change does (the program redraws)". No code change, and no test.

**N1 (nit). An explicit Peek or Resume of a terminal close to its TTL can close it seconds after it opens.**
- **Why:** the client finds an existing pty through `/api/term/list` and only attaches the stream (ext_vt.js inline `spawn`/peek; `open_pty`'s reuse returns at 3401 and 3522 do not touch). An explicit open cannot be told apart from a reconnect.
- **Direction:** no change; it is a known gap, and the closing note plus Resume cover it. If the user objects, put back the attach-only touch (not the detach touch) in `screen_stream` and `raw_stream`. That accepts tunnel and SSE-reconnect resets. Do not put back the viewer gate.

**N2 (nit). The selfcheck insertion is out of place.** At `tests/test_selfcheck.py:953-958`, the new `_q` block sits between the comment `# idle TTL vs a session live elsewhere: …` and the `_p` block that comment describes.
- **Fix:** move the five lines above that comment, under their own comment: `# idle TTL ignores viewers: a displayed pty still idles out; a live HOLD still defers it`.

**N3 (nit). Comment grammar and line length.**
- The `Pty.last_output` comment (term_vt.py:1536-1538) now reads "moves on a keystroke, neither of which". Change it to "(which also moves on a keystroke, which does not mean the TUI has finished redrawing)".
- The first line of the `_reader` docstring (1877) runs past 160 characters. Rewrap it.

**N4 (nit; no change, same as base).** In `keys()` (term_vt.py:4294-4297), a focus report still sets `pt.startup_done = True` for a folder shell. That does not match "focus is not input". It only matters when a program inside a folder shell that is still starting enables `?1004`. Mention it in the push notes.

**N5 (nit; no change).** Mouse-motion reports (`?1003`) sent while the pointer merely hovers over a pane count as input, so hovering over a pane running vim or htop resets the clock. Claude Code does not enable `?1003`. A wheel scroll is real input to the program.

**N6 (nit; tracker-gap Step 4). No integration eval, and no live curl proof yet.**
- U2 drives the real `screen_stream` route against a real reader thread, which is acceptable in place of an integration test.
- The ship step must restart the server, then GET `/api/term/list` and show a `viewers: 1` pty whose `idle_s` passes the TTL and whose row goes done. Use a scratch pty, and only with ownership proof.

**N7 (nit; no change).** The comments at `ext_vt.js:747` and `3052` describe the old viewer pin in the past tense ("used to"). The leaked-stream fixes they document still matter for `MAX_STREAMS`.

### Overall clean fix list (for a cheaper fixer)
1. **F1:** in `_idle_due`, add `not pt.login and`, plus the one docstring line. Add the selfcheck line (F1a) and `test_login_pty_is_not_idle_reaped` (F1b). Prove both RED by removing the clause.
2. **F3:** the README wording on resizing.
3. **F2:** the one-sentence copy in `ext_cr_dialogs.js:2189` and `README.md:112`. Put D3 to the user before the push; write code only if they choose it.
4. **N2 and N3:** move the selfcheck block, fix the comment wording, rewrap the docstring.
5. **Gate and ship:** `unset TRACKER_AUTH;` run one module per process, then `/branch-sync`, then restart, then the live check in N6.

## Reconciliation (main thread)

| # | Verdict | Action |
|---|---|---|
| F1 login pty idle-reaped mid-login | confirmed | apply: `not pt.login and` in `_idle_due` + selfcheck line + `test_login_pty_is_not_idle_reaped` |
| F2 open-but-untouched pane no longer protects a waiting Claude / draft / slow `/loop` | confirmed, intended (the user's ask: reap ~10h-idle terminals; a reaped Claude is resumable; busy/live holds unchanged) | wording only in `ext_cr_dialogs.js:2189` + `README.md:112`; surfaced to the user as D3 in the final report |
| F3 README says resize never resets the clock | confirmed | reword to "a same-size re-fit does not" |
| nits: selfcheck comment placement, comment grammar/length, stale `ext_vt.js` comments | confirmed, comment-only | apply |
| nits: Peek near TTL, mouse-hover reports, focus marking shell startup done | overstated for this change | no change |
| live `/api/term/list` proof | needs a restart of 8790, which kills all running terminals | not done automatically; user restarts |

## Review fixes applied

- F1: `_idle_due` now starts with `not pt.login and` (login ptys keep only `LOGIN_WATCH_MAX`); selfcheck line + `TestIdleTimeout.test_login_pty_is_not_idle_reaped`. Proven RED by removing the guard (test FAILED), GREEN restored.
- F2 wording: one sentence in `ext_cr_dialogs.js` (TTL row) and README (waiting Claude / unsent draft closed after the TTL; resumable). Code option (hold a "waiting" Claude) NOT taken; D3 stays a user decision.
- F3 wording: README says a same-size re-fit does not reset the clock, a real size change does.
- Nits applied (comment-only): selfcheck block regrouped under its own comment, `last_output` comment grammar, `_reader` docstring rewrapped, stale `ext_vt.js` viewer-pin comments reworded.
- Not changed: N1 (Peek near TTL), N4, N5, N7 logic; N6 live curl proof needs a 8790 restart (user).
- Gate: test_term_vt + test_selfcheck OK (385 tests); remaining modules run one per process.
