PORT ?= 8787
.PHONY: help serve stop check test hooks bundle

help:
	@echo "make serve | stop | check | test | hooks | bundle   (PORT=$(PORT))"

serve: stop
	@echo "Starting AI session tracker on http://localhost:$(PORT)"
	@PORT=$(PORT) python3 -m aitracker

stop:
	@pid=$$(lsof -nP -iTCP:$(PORT) -sTCP:LISTEN -t 2>/dev/null); \
	if [ -n "$$pid" ]; then echo "Stopping :$(PORT) (pid $$pid)"; kill $$pid; sleep 1; \
	else echo "Nothing running on :$(PORT)"; fi

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
