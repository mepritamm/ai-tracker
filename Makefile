PORT ?= 8787
.PHONY: help serve stop check test hooks bundle

help:
	@echo "make serve | stop | check | test | hooks | bundle    (override port: PORT=9000)"

serve: stop
	@echo "Starting AI session tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 -m aitracker

stop:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Stopping :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; \
	else echo "Nothing running on :$(PORT)"; fi

# the mandatory gate: the full unittest suite (unit tests + evals + selfcheck smoke)
check test:
	@python3 -m unittest discover -s tests -t .

# install the pre-commit hook that blocks commits failing `make check`
hooks:
	@cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit && echo "pre-commit hook installed"

bundle:
	@python3 scripts/bundle.py
