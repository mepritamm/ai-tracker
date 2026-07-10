PORT ?= 8787
.PHONY: help serve stop check bundle

help:
	@echo "make serve | stop | check | bundle    (override port: PORT=9000)"

serve: stop
	@echo "Starting AI session tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 -m aitracker

stop:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Stopping :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; \
	else echo "Nothing running on :$(PORT)"; fi

check:
	@python3 -m unittest discover -s tests

bundle:
	@python3 scripts/bundle.py
