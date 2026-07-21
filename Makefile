PORT ?= 8787
TUNNEL_PORT ?= 8790
.PHONY: help serve stop tunnel check test hooks bundle

help:
	@echo "make serve | stop | tunnel | check | test | hooks | bundle   (PORT=$(PORT))"

serve:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Freeing :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; fi
	@echo "Starting AI session tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 -m aitracker

# stop everything: local tracker, the authed tunnel instance, and the Cloudflare tunnel
stop:
	@for p in $(PORT) $(TUNNEL_PORT); do \
	  pid=$$(lsof -nP -iTCP:$$p -sTCP:LISTEN -t 2>/dev/null); \
	  if [ -n "$$pid" ]; then echo "Stopping :$$p (pid $$pid)"; kill $$pid; fi; \
	done
	@pkill -f "cloudflared tunnel --url http://localhost:$(TUNNEL_PORT)" 2>/dev/null && echo "Stopped Cloudflare tunnel" || true

# public remote access — authed tracker on TUNNEL_PORT + a free Cloudflare quick tunnel; prints the URL.
# Needs TRACKER_AUTH="user:pass" (the URL is public) and cloudflared (brew install cloudflared).
tunnel:
	@test -n "$$TRACKER_AUTH" || { echo 'set TRACKER_AUTH="user:pass" first — the tunnel URL is public'; exit 1; }
	@command -v cloudflared >/dev/null || { echo "cloudflared not found — run: brew install cloudflared"; exit 1; }
	@pid=$$(lsof -nP -iTCP:$(TUNNEL_PORT) -sTCP:LISTEN -t 2>/dev/null); if [ -n "$$pid" ]; then kill $$pid; sleep 1; fi
	@pkill -f "cloudflared tunnel --url http://localhost:$(TUNNEL_PORT)" 2>/dev/null || true
	@TRACKER_AUTH="$$TRACKER_AUTH" PORT=$(TUNNEL_PORT) HOST=127.0.0.1 nohup python3 -m aitracker >/tmp/aitracker-tunnel.log 2>&1 &
	@sleep 2
	@nohup cloudflared tunnel --url http://localhost:$(TUNNEL_PORT) >/tmp/aitracker-cf.log 2>&1 &
	@printf "waiting for the Cloudflare URL"; url=""; \
	for i in $$(seq 1 20); do url=$$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/aitracker-cf.log 2>/dev/null | head -1); [ -n "$$url" ] && break; printf "."; sleep 2; done; echo; \
	if [ -n "$$url" ]; then echo "  -> $$url   (log in with your TRACKER_AUTH)"; else echo "  (no URL yet; see /tmp/aitracker-cf.log — this network may block Cloudflare)"; fi

# the mandatory gate — the whole suite (unit + evals + server + selfcheck smoke)
check test:
	@python3 -m unittest discover -s tests -t .

# install the pre-commit gate (blocks commits that fail `make check`)
hooks:
	@cp hooks/pre-commit "$$(git rev-parse --git-common-dir)/hooks/pre-commit"
	@chmod +x "$$(git rev-parse --git-common-dir)/hooks/pre-commit"
	@echo "pre-commit gate installed."

bundle:
	@python3 scripts/bundle.py
