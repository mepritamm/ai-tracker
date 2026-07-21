# Remote & mobile access — track your agents on the go

The tracker is a **local, read-only** dashboard. By default it binds to `127.0.0.1` (localhost only) with
no login — nothing is reachable off your machine. This guide shows how to safely reach it from a phone or
tablet, install it as an app, and require a password.

Three things combine here, each independent:

1. **Connectivity** — how the phone reaches your Mac (Tailscale / Cloudflare Tunnel / ngrok / same-Wi-Fi).
2. **Auth** — an optional password on every route (`TRACKER_AUTH`).
3. **Install & feel** — Add to Home Screen (PWA), responsive phone/tablet layout, local-only flagging.

---

## TL;DR

**Just running it locally? `make serve` — done** (http://localhost:8787, no tunnel, no login). Everything
below is only for reaching it from *another* device; the tracker stays localhost-only until you opt in.

```bash
# Free tunnel that works through most corporate firewalls (ngrok/Tailscale blocked): set a password, then
TRACKER_AUTH="you:pick-a-strong-pass" make tunnel      # prints a https://…trycloudflare.com URL for your phone

# Or a private Tailscale mesh (stable URL, no public exposure):
TRACKER_AUTH="you:pick-a-strong-pass" HOST=0.0.0.0 make serve
# then on the phone open  http://<your-mac-name>:8787  (Tailscale MagicDNS)
```

| Env var | Default | Set it to… |
|---|---|---|
| `HOST` | `127.0.0.1` (localhost only) | `0.0.0.0` to accept connections from LAN / Tailscale |
| `TRACKER_AUTH` | *(empty — off)* | `"user:pass"` to require HTTP Basic Auth on **every** route |
| `PORT` | `8787` | any free port |

`HOST` and `TRACKER_AUTH` are **off by default** — local development is completely unchanged unless you
opt in.

> **On a restrictive / corporate network?** Many block VPN meshes (Tailscale) and ngrok outright.
> **Cloudflare Tunnel** (Option D) usually still gets through — it rides Cloudflare's edge over 443/QUIC and
> looks like ordinary web traffic. Blocks are often *domain*-specific, so if one provider is refused, try
> another (Cloudflare, then `npx tunnelmole 8790`) before giving up. SSH-based tunnels (serveo, pinggy) tend
> to be reset by the same firewalls.

---

## Security model (read this first)

- **Auth is one gate for every path.** `TRACKER_AUTH` is checked in the HTTP handler, so it covers every
  route (`/`, `/api/*`) and both providers (Claude, Auggie) uniformly — localhost, LAN, Tailscale, or
  ngrok. Credentials are compared in constant time.
- **The tracker only reads** your session logs and makes **no outbound network calls.** The only way data
  leaves the machine is through the tunnel/network path *you* set up below.
- **Flagging is desk-only.** The "🚩 Flag an issue or gap" button is hidden automatically when the
  dashboard is opened from any non-localhost host (phone/tablet). Existing flags stay **viewable** —
  you just can't file new ones remotely. (Detected via `location.hostname`, which — unlike the server —
  can tell a tunneled phone from a local browser.)
- **Basic Auth is only as private as the transport.** Over HTTPS (ngrok) or an encrypted mesh (Tailscale)
  it's safe. Over **plain-HTTP LAN** the header is base64 (not encrypted) — fine on a trusted home
  network, not on public Wi-Fi.

---

## Option A — Tailscale (recommended for "on the go")

A free, private WireGuard mesh: only *your* devices can see each other, from anywhere. No public exposure.

1. Install Tailscale on the **Mac** and the **phone/tablet**, sign in to the same account on both.
2. On the Mac, start the tracker bound for the mesh, with a password:
   ```bash
   TRACKER_AUTH="you:pick-a-strong-pass" HOST=0.0.0.0 make serve
   ```
3. Find your Mac's Tailscale name (MagicDNS) — e.g. `pritams-mac` — in the Tailscale app.
4. On the phone open `http://pritams-mac:8787`, enter the username/password.

The Tailscale name never changes, so the Home-Screen icon (below) keeps working across restarts. This is
the best fit for the tracker's "nothing leaves the machine to strangers" design.

---

## Option B — ngrok (public HTTPS tunnel)

A public URL that forwards to your localhost. Convenient, but it puts your dashboard on the public internet
— so a password is **mandatory**.

1. One-time: sign up free at `dashboard.ngrok.com`, then `ngrok config add-authtoken <YOUR_TOKEN>`.
   (Optional but recommended: claim your one free **static domain** so the URL is stable.)
2. Start the tracker **with a password** (no `HOST` change needed — ngrok reaches it via localhost):
   ```bash
   TRACKER_AUTH="you:pick-a-strong-pass" make serve
   ```
3. In another terminal, open the tunnel:
   ```bash
   ngrok http 8787
   # or, with your reserved domain:  ngrok http --domain=your-name.ngrok-free.app 8787
   ```
4. Open the `https://…ngrok-free.app` URL on the phone (click through ngrok's one-time warning), enter the
   password.

Because the app enforces `TRACKER_AUTH`, you don't also need ngrok's `--basic-auth` — one password covers
it. Never run an ngrok tunnel to the tracker **without** `TRACKER_AUTH`.

---

## Option C — Same Wi-Fi (LAN)

Simplest, but only works while the phone is on the **same network** as the Mac (not truly "on the go").

1. Start bound to all interfaces, with a password:
   ```bash
   TRACKER_AUTH="you:pick-a-strong-pass" HOST=0.0.0.0 make serve
   ```
2. Find the Mac's LAN IP: `ipconfig getifaddr en0` (e.g. `192.168.1.105`).
3. On the phone open `http://192.168.1.105:8787`, enter the password.

---

## Option D — Cloudflare Tunnel (free, gets through most corporate firewalls)

A free public HTTPS tunnel over Cloudflare's edge. No account for a **quick tunnel**, no interstitial, and
it commonly works where ngrok/Tailscale are blocked.

1. Install once: `brew install cloudflared`.
2. Start an **authed** tracker on a dedicated port (keeps your local `:8787` untouched):
   ```bash
   TRACKER_AUTH="you:pick-a-strong-pass" PORT=8790 python3 -m aitracker &
   ```
3. Open the quick tunnel — it prints a `https://<random>.trycloudflare.com` URL:
   ```bash
   cloudflared tunnel --url http://localhost:8790
   ```
4. Open that URL on the phone and enter the password.

The quick-tunnel URL is **random each run** (rotates on restart) — for a stable one see **A permanent URL**
below. Free backup with the same properties (also no account): `npx tunnelmole 8790`.

---

## Run it yourself — one-command start & stop

The Makefile wraps the Cloudflare flow once `cloudflared` is installed:

```bash
TRACKER_AUTH="you:pick-a-strong-pass" make tunnel   # authed tracker (:8790) + Cloudflare tunnel; prints the URL
make stop                                            # stops the tracker AND the tunnel
```

`make tunnel` refuses to start without `TRACKER_AUTH` (the URL is public). `make stop` tears down the local
tracker, the authed `:8790` instance, and any `cloudflared` tunnel. Raw equivalents if you prefer:

```bash
# start
TRACKER_AUTH="you:pass" PORT=8790 nohup python3 -m aitracker >/tmp/aitracker-tunnel.log 2>&1 &
nohup cloudflared tunnel --url http://localhost:8790 >/tmp/cf.log 2>&1 &
grep -m1 -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log   # your URL
# stop
pkill -f "cloudflared tunnel"; lsof -ti:8790 | xargs kill
```

To keep it alive while you're away, prevent the Mac sleeping: `caffeinate -i -s &` (Ctrl-C or `killall
caffeinate` to release). Note the lid staying open / on power — closing the lid sleeps regardless.

---

## A permanent (non-rotating) URL

Quick tunnels (Cloudflare, tunnelmole) mint a **new URL each run**, so a home-screen icon breaks after a
restart. For a URL that never changes, use a Cloudflare **named tunnel** — free, but it needs a domain on
your Cloudflare account plus a one-time browser login:

```bash
cloudflared tunnel login                              # one-time, opens a browser
cloudflared tunnel create ai-tracker
cloudflared tunnel route dns ai-tracker tracker.<yourdomain>
# ~/.cloudflared/config.yml:
#   tunnel: ai-tracker
#   credentials-file: ~/.cloudflared/<UUID>.json
#   ingress:
#     - hostname: tracker.<yourdomain>
#       service: http://localhost:8790
#     - service: http_status:404
cloudflared tunnel run ai-tracker                     # same URL every time (or: sudo cloudflared service install)
```

`https://tracker.<yourdomain>` never rotates — add it to the home screen once, keep `TRACKER_AUTH` on the
tracker. No domain? `zrok` (free, needs an account) gives a reserved stable URL as an alternative.

---

## Install it as an app (Add to Home Screen)

Once the dashboard opens on the phone/tablet (any option above), install it so it launches fullscreen like
a native app:

- **iPhone / iPad (Safari):** Share → **Add to Home Screen** → *Add*. You get an "AI Tracker" icon.
- **Android (Chrome):** ⋮ menu → **Install app** / **Add to Home screen**.

The layout is responsive: a phone gets a stacked single-column view; a tablet (iPad / Android, portrait or
landscape) gets the master-detail sidebar-beside-content layout.

---

## Notifications?

There are none by design — the tracker makes no outbound calls, so it won't push to your phone when an
agent finishes. The in-app completion 🔔 only fires with a tab open. "On the go" means *you glance at it*,
not *it pings you*. Adding push would mean an outbound integration, a deliberate departure from the
read-only, nothing-leaves-the-machine model.

---

## Troubleshooting

- **Phone can't connect (LAN/Tailscale):** you forgot `HOST=0.0.0.0` — the default `127.0.0.1` refuses
  non-local connections. (ngrok doesn't need it.)
- **No password prompt:** `TRACKER_AUTH` wasn't set in the *same* shell that launched the server. Confirm
  with `ai-tracker --help` (it lists the env vars) and relaunch.
- **Home-Screen icon points at a dead URL:** you used ngrok's *random* URL; claim a static domain, or use
  Tailscale (its name is stable).
- **Flag button missing on the phone:** that's intentional — flagging is local-only. Use the Mac.
- **ngrok / Tailscale won't connect on this network:** it's blocked (common on corp/office Wi-Fi). Use
  **Option D (Cloudflare Tunnel)** — it usually passes. If Cloudflare is also refused, try `npx tunnelmole 8790`.
- **`make tunnel` says "set TRACKER_AUTH":** it won't start a public tunnel without a password. Prefix the
  command: `TRACKER_AUTH="you:pass" make tunnel`.
