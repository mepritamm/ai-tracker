# ai-tracker
PORT ?= 8787

.PHONY: serve stop check test hooks help

help:
	@echo "make serve   start (or cleanly restart) the tracker on http://localhost:$(PORT)"
	@echo "make stop    stop the tracker running on :$(PORT)"
	@echo "make check   the gate: --selfcheck + the unit-test suite (must be green)"
	@echo "make test    run just the unit-test suite (test_tracker.py)"
	@echo "make hooks   install the pre-commit gate (runs the tests before every commit)"
	@echo "             (override the port with: make serve PORT=9000)"

serve: stop
	@echo "Starting tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 tracker.py

stop:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Stopping tracker on :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; \
	else echo "No tracker running on :$(PORT)"; fi

# The gate — both must be green before any code lands (see `make hooks`).
check: test
	@python3 tracker.py --selfcheck

test:
	@python3 -W ignore::ResourceWarning -m unittest -q test_tracker

# Install the shared pre-commit hook (works from any worktree / fresh clone).
hooks:
	@hookdir="$$(git rev-parse --git-common-dir)/hooks"; \
	cp hooks/pre-commit "$$hookdir/pre-commit"; chmod +x "$$hookdir/pre-commit"; \
	echo "pre-commit gate installed -> $$hookdir/pre-commit"
