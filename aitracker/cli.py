"""ai-tracker CLI: serve the dashboard, or run the self-check."""
import json
import os
import sys

from . import __version__, config
from .server import run, _port_busy
from .pending import cli_main
from .schedule import svc_install, svc_uninstall, svc_status, svc_baked, svc_spawn_deferred, svc_log_path

HELP = """ai-tracker — live dashboard for AI coding sessions (Claude Code, Auggie, …).

Usage: ai-tracker [--serve | --selfcheck | --version | --help]
       --serve   install as a background service on 8790 (or the next free port; the port stays locked), then return;
                 runs in the foreground instead in a worktree / off macOS
       ai-tracker [--install-service | --reinstall-service | --uninstall-service | --service-status]   (macOS LaunchAgent)
       ai-tracker --pending [--dry-run] [--json] [--if-due] [--install-scheduler] [--uninstall-scheduler] [--scheduler-status]
Env:   PORT          (default 8790)
       HOST          bind address (default 127.0.0.1; use 0.0.0.0 for LAN/Tailscale access)
       TRACKER_AUTH  "user:pass" to require HTTP Basic Auth on every route (default off)
       TRACKER_TUNNEL_READONLY=1  make every non-local caller (tunnel/Tailscale/LAN) view-only; cannot be
                     switched off from config. Header-less forwarders (ssh -R, VS Code port-forward)
                     look local and are NOT covered.
"""


def _selfcheck():
    import unittest
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suite = unittest.TestLoader().discover(os.path.join(here, "tests"), top_level_dir=here)
    ok = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
    if ok:
        print("selfcheck ok")
    sys.exit(0 if ok else 1)


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        print("ai-tracker", __version__)
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP.strip())
        return
    if "--selfcheck" in sys.argv:
        _selfcheck()
        return
    if "--pending" in sys.argv:
        sys.exit(cli_main(sys.argv[1:]))
    port = int(os.environ.get("PORT", 8790))
    host = os.environ.get("HOST", "127.0.0.1")   # 0.0.0.0 to reach it from a phone/tablet on LAN/Tailscale
    in_svc = bool(os.environ.get("AITRACKER_SERVICE_PID"))   # run from a dashboard terminal: bootout would kill us
    if in_svc and ("--serve" in sys.argv or "--install-service" in sys.argv or "--reinstall-service" in sys.argv):
        config.SERVICE = True       # write the plist only; the detached helper does launchctl
    if "--serve" in sys.argv:
        if os.environ.get("TRACKER_AUTH"):
            print("ai-tracker: note: TRACKER_AUTH is not carried into the background service (loopback-only, no login)", file=sys.stderr)
        baked = svc_baked()
        if baked and "PORT" not in os.environ:
            port = baked[0]         # locked port from the first install; HOST still comes from the env
        if not baked or port != baked[0] or host != baked[1]:
            port = next((p for p in range(port, port + 20) if not _port_busy(host, p)), port)
        rc = svc_install(port, host)
        if rc == 3:
            svc_spawn_deferred(True)
            print("ai-tracker: deferred: the service restarts in about 2 s")
            rc = 0
        if rc == 0:
            print(f"ai-tracker: installed as a background service on http://localhost:{port} "
                  f"(port locked; `make service-uninstall` to remove); log: {svc_log_path()}")
            sys.exit(0)
        if rc == 1:
            print(f"ai-tracker: service install failed; see {svc_log_path()} or run make service-status")
            sys.exit(1)
        print("ai-tracker: cannot install as a service here; running in the foreground instead")
    if "--install-service" in sys.argv or "--reinstall-service" in sys.argv:
        if "--reinstall-service" in sys.argv and "PORT" not in os.environ:
            port, host = svc_baked() or (port, host)
        rc = svc_install(port, host)
        if rc == 3:
            svc_spawn_deferred(True)
            print("ai-tracker: deferred: the service restarts in about 2 s")
            rc = 0
        sys.exit(rc)
    if "--uninstall-service" in sys.argv:
        sys.exit(svc_uninstall())
    if "--service-status" in sys.argv:
        print(json.dumps(svc_status()))
        return
    service = "--service" in sys.argv   # internal: the LaunchAgent's flag (strict port, no browser, no tunnel)
    run(host=host, port=port, open_browser=not service and not os.environ.get("TRACKER_NO_BROWSER"), service=service)   # run() picks the next free port if this one is busy, and opens the browser
