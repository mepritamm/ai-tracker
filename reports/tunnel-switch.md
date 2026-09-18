# Tunnel switch — contract & outcome

Branch: worktree-tunnel-switch → pushed to personal/main as 3d2f9ad (2026-09-18).

## Contract (verbatim from user) — verdicts
1. "add an additional switch for tunnel which would generate the tunnel with username and password their
   respective parameters and then then public URL is generated, which can be copied and all of those
   functionalities" — **discharged**: Config → Tunnel toggle → `POST /api/tunnel/ctl start`; URL in a
   `<code>` with Copy; creds auto-generated when blank and shown once.
2. "enabling everyone to do a `make serve` and generate a tunnel on demand from the config, such that they
   dont have stop the current serve and start another with `make tunnel` command" — **discharged**: the
   running server spawns cloudflared itself (`aitracker/tunnel.py`); proven live on port 8799.
3. "dont add a turn off that single toggle for tunnel which opens and closes will do the work" —
   **discharged**: one `toggleCtl`, on=start / off=stop; no separate button.
4. "the tunnel automatically closes after 12hour" — **discharged**: `TUNNEL_TTL = 43200`, `threading.Timer`
   → `stop()`; UI shows "open until HH:MM"; `TestTTL` (TTL shrunk to 0.5 s) asserts auto-close + TUNNEL_ON
   false.
5. "the URL is auto-rotable" — **discharged**: every start mints a new address; "Rotate URL" = stop+start;
   `TestRotate` + live run (new URL differed).
6. "username and password can be again rotated" — **discharged**: "Rotate credentials" →
   `rotate_creds` mints a random pair, applies live to tunnel traffic (cookies keyed on the request's cred,
   so old logins are signed out); fields stay editable.
7. /tracker-gap: eval + unit tests, make check green, README updated — **discharged**: tests/test_tunnel.py
   (33), TestBundle `_save_json`, page-build no-hostname-gate assertion, selfcheck assertions; per-module
   gate 70/70 + hook gate green; README + docs/remote-access.md.
8. /tracker-push: commit on main, push personal/main, LICENSE present — **discharged**: 3d2f9ad pushed
   directly (EMU account cannot open PRs); `LICENSE ok`; no data files on the remote. The PRIMARY checkout's
   local `main` still needs `git pull --ff-only personal main`.

## Head-out decisions
- Auth hot-applies to **tunnel traffic only** (`Cf-Connecting-Ip`/`Cf-Ray`); localhost/LAN keep
  `TRACKER_AUTH`. A tunnel request with no credential is refused.
- Rotate button + editable fields; blank creds on switch-on → auto-generated.
- `TUNNEL_ON` persists across a server exit (SIGTERM/atexit keep it; only the switch and the TTL clear it);
  `make serve` re-mints the tunnel and the SPA shows a one-time popup that opens Config → Tunnel.

## Verification trail
- Live (real cloudflared): no-auth → 401 + login page; wrong pass → 401; right creds → 200 dashboard;
  localhost → 200; rotate → new URL; rotate_creds → new pair; stop → cleared; SIGTERM server → child dead,
  TUNNEL_ON kept; restart → new URL, `autostarted: true`, console notice; no orphans.
- Review rounds: sonnet (UI/contract) 2 defects fixed; opus (server) 5 defects fixed; opus re-verify 3
  follow-ups fixed (keep-on-exit, kill-before-write, RLock) + bundle HEADER gaps.
- Own find: a no-op `stop()` from any importing process (tests, --selfcheck, bundle) wiped the running
  server's config — fixed, regression test proven red-on-revert.

## Known limits / parked
- A fresh `*.trycloudflare.com` hostname can take a minute+ to resolve on some resolvers (VPN DNS
  negative-caches early misses) — documented in README.
- A direct LAN request that forges `Cf-Ray` is judged against the tunnel creds (by design of the
  header-based routing the user chose); rotate creds to revoke a shared link.
- The share link exposes the in-browser terminal (a shell on this machine) — README says treat it like an
  SSH key.
