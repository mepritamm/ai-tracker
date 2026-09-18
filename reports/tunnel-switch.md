# Tunnel switch — contract & progress

Branch: worktree-tunnel-switch. Started 2026-09-18.

## Contract (verbatim from user)
1. "add an additional switch for tunnel which would generate the tunnel with username and password their
   respective parameters and then then public URL is generated, which can be copied and all of those
   functionalities" — [ ] not discharged
2. "enabling everyone to do a `make serve` and generate a tunnel on demand from the config, such that they
   dont have stop the current serve and start another with `make tunnel` command" — [ ] not discharged
3. "dont add a turn off that single toggle for tunnel which opens and closes will do the work" (supersedes
   the earlier "turn off button" ask) — [ ] not discharged
4. "the tunnel automatically closes after 12hour" — [ ] not discharged
5. "the URL is auto-rotable" — [ ] not discharged
6. "username and password can be again rotated" — [ ] not discharged
7. /tracker-gap: eval + unit tests, make check green, README updated — [ ] not discharged
8. /tracker-push: commit on main, push personal/main, LICENSE present — [ ] not discharged

## Decisions (head-out answers, 2026-09-18)
- Auth hot-applies to **tunnel traffic only** (requests carrying cloudflared's `Cf-Connecting-Ip`/`Cf-Ray`);
  localhost/LAN keep `TRACKER_AUTH`. Tunnel request with no creds staged → refused.
- Rotate button + editable fields; blank creds on switch-on → auto-generated (never an open tunnel).
- `TUNNEL_ON` persisted; on `make serve` restart the tunnel re-mints automatically and the SPA shows a
  one-time popup linking to Config → Tunnel.
- Single toggle, no separate off button. 12 h TTL = `tunnel.TUNNEL_TTL`.

## Design
- `aitracker/tunnel.py`: start/stop/rotate/status/autostart/rotate_creds/ensure_creds/via_tunnel/cred;
  Popen cloudflared, stderr reader → `TUNNEL_URL` in config.json; Timer TTL; atexit kill.
- `server.py`: `_cred()` per request; `_sign/_make_token/_token_ok` keyed on the request's cred;
  `GET /api/tunnel` merges `tunnel.status()`; `POST /api/tunnel/ctl {action}`; `run()` → `tunnel.autostart`.
- UI in `ext_cr_dialogs.js`: toggle row, URL code+Copy+Rotate URL, Rotate credentials, polling, boot toast.

## Progress
- worktree created; Explore (sonnet) mapping tunnel/auth/config seam; researcher (haiku) on cloudflared output.
- A (sonnet) server side + tests/test_tunnel.py; C (sonnet) UI; D (haiku) docs — all landed.
- Integration defect found by live run: `tunnel.stop()` (atexit in EVERY importing process) wiped the running
  server's TUNNEL_ON/URL. Fixed: stop() writes config.json only when this process owns a tunnel; regression
  test `test_noop_stop_leaves_another_processes_state_alone` proven red-on-revert.
- UI reviewer (sonnet): 2 confirmed defects (error body replacing tunnel state; stale footer sentence) → sweeper.
- LIVE PROOF (real cloudflared, port 8799, curl --resolve via 1.1.1.1 because the VPN resolver negative-caches
  new hostnames): tunnel no-auth → 401 + login page; wrong pass → 401; right creds → 200 dashboard;
  localhost no-auth → 200; rotate → new URL; rotate_creds → new pair; stop → on:false, config cleared.
  Note for users: a fresh quick-tunnel hostname can take a minute+ to resolve on some resolvers.
- Opus reviewer round 1: 5 confirmed lifecycle defects (SIGTERM orphan, bundle HEADER, reader lock, child
  self-exit state, hard-coded origin) → sonnet fixer; test_tunnel 30 tests.
- Gate (per-module, 71 modules): 70 OK, test_selfcheck "NO TESTS RAN" (not a unittest module; test_tracker
  wraps it and prints `selfcheck ok`), bundle OK, node --check OK.
- Opus re-verify: 1/3/4/5 fixed; follow-ups → sonnet fixer #2: keep TUNNEL_ON on process exit (else the
  auto-restart contract never fires after `make stop`), kill-before-write ordering, RLock, bundle HEADER
  uuid/fcntl/urllib (+ TestBundle _save_json test).
