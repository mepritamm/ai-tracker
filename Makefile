# Claude Code Session Tracker
PORT ?= 8787

.PHONY: serve stop check help

help:
	@echo "make serve   start (or cleanly restart) the tracker on http://localhost:$(PORT)"
	@echo "make stop    stop the tracker running on :$(PORT)"
	@echo "make check   run the built-in self-check"
	@echo "             (override the port with: make serve PORT=9000)"

serve: stop
	@echo "Starting tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 tracker.py

stop:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Stopping tracker on :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; \
	else echo "No tracker running on :$(PORT)"; fi

check:
	@python3 tracker.py --selfcheck
