# KlariticsAI (Python service). Every command lives here. `make help` lists them.
SHELL := /bin/bash
.DEFAULT_GOAL := help
UV ?= uv
STATE := .bearing/state
SKIPPED := $(STATE)/.skipped
# The gates `make check` runs, in order.
GATES := format-check lint typecheck test vuln
STORE_PATH ?= data/klaritics.duckdb

# $(call skip,gate,tool): the tool is absent. Print it, record it, and let the
# other gates run; `check` fails on any recorded skip. Never a silent pass.
define skip
{ mkdir -p $(STATE); echo "$(1): SKIPPED ($(2) not installed)"; echo "$(1) $(2)" >> $(SKIPPED); exit 0; }
endef
# $(call need_tool,gate,tool): uv, then the project tool inside the venv.
define need_tool
command -v $(UV) >/dev/null || $(call skip,$(1),uv); $(UV) run --quiet $(2) --version >/dev/null 2>&1 || $(call skip,$(1),$(2))
endef

.PHONY: help setup dev seed mcp mcp-http mcp-dev ask eval eval-record up check check-file fix test lint typecheck format format-check vuln doctor clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install Python 3.14, dependencies (writes uv.lock) and git hooks
	$(UV) python install 3.14
	@if [ -f uv.lock ]; then $(UV) sync --locked --all-groups; else echo "setup: no uv.lock yet, resolving; commit the lockfile it writes"; $(UV) sync --all-groups; fi
	bash .githooks/install.sh
	@echo "setup: the committed .githooks run on commit; .pre-commit-config.yaml is for 'uv run pre-commit run --all-files'"
	@echo "setup done"

dev: ## Run the API locally with reload (reads .env if present)
	@set -a; [ -f .env ] && . ./.env; set +a; $(UV) run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port "$${PORT:-8080}"

seed: ## Build the event store: 20,000 users, 60 days, three planted scenarios (seed 42)
	$(UV) run python -m app.seed --path "$(STORE_PATH)"

mcp: ## Run the MCP server over stdio (needs make seed)
	@STORE_PATH="$(STORE_PATH)" $(UV) run python -m app.mcp_server --transport stdio

mcp-http: ## Run the MCP server over streamable HTTP at :8090/mcp (needs MCP_HTTP_TOKEN)
	@set -a; [ -f .env ] && . ./.env; set +a; STORE_PATH="$(STORE_PATH)" $(UV) run python -m app.mcp_server --transport http

mcp-dev: ## Open the MCP Inspector against the stdio server (needs Node)
	npx -y @modelcontextprotocol/inspector $(UV) run python -m app.mcp_server --transport stdio

ask: ## Ask the analyst one question: make ask Q="Why did purchases drop last week?" (needs OPENROUTER_API_KEY, or LLM_MODE=replay)
	@[ -n "$(Q)" ] || { echo 'usage: make ask Q="Why did purchases drop last week?"' >&2; exit 2; }
	@set -a; [ -f .env ] && . ./.env; set +a; STORE_PATH="$(STORE_PATH)" $(UV) run python -m app.agent "$(Q)"

eval: ## Analyst eval on recorded model answers (no network); fails below evals/analyst/gate.json
	@[ -f "$(STORE_PATH)" ] || $(MAKE) --no-print-directory seed
	STORE_PATH="$(STORE_PATH)" LLM_MODE=replay $(UV) run python -m evals.analyst.run

eval-record: ## Record the eval's model answers live (needs OPENROUTER_API_KEY; spends against LLM_BUDGET_USD)
	@[ -f "$(STORE_PATH)" ] || $(MAKE) --no-print-directory seed
	@set -a; [ -f .env ] && . ./.env; set +a; STORE_PATH="$(STORE_PATH)" $(UV) run python -m evals.analyst.run --mode record

up: ## Build and run the API and the MCP server in Docker (the image seeds its own store)
	docker compose up --build

format: ## Format
	$(UV) run ruff format .

format-check: ## Fail if any file is unformatted
	@n=$$(git ls-files -co --exclude-standard '*.py' | wc -l | tr -d ' '); \
	[ "$$n" -gt 0 ] || { echo "format-check: 0 python files, nothing checked" >&2; exit 1; }; \
	$(call need_tool,format-check,ruff); \
	$(UV) run ruff format --check . || { echo "format-check: run make fix" >&2; exit 1; }; \
	echo "format-check: $$n files checked"

lint: ## ruff check
	@n=$$(git ls-files -co --exclude-standard '*.py' | wc -l | tr -d ' '); \
	[ "$$n" -gt 0 ] || { echo "lint: 0 python files, nothing checked" >&2; exit 1; }; \
	$(call need_tool,lint,ruff); \
	$(UV) run ruff check . && echo "lint: $$n files checked"

typecheck: ## mypy strict
	@n=$$(git ls-files -co --exclude-standard 'app/*.py' 'tests/*.py' 'evals/*.py' | wc -l | tr -d ' '); \
	[ "$$n" -gt 0 ] || { echo "typecheck: 0 python files, nothing checked" >&2; exit 1; }; \
	$(call need_tool,typecheck,mypy); \
	$(UV) run mypy app tests evals && echo "typecheck: $$n files checked"

test: ## All tests with coverage; the first run builds the cached test store under .cache/
	@n=$$(git ls-files -co --exclude-standard 'tests/test_*.py' 'tests/**/test_*.py' | wc -l | tr -d ' '); \
	[ "$$n" -gt 0 ] || { echo "test: 0 test files, nothing checked" >&2; exit 1; }; \
	$(call need_tool,test,pytest); \
	set -o pipefail; $(UV) run pytest 2>&1 | tail -60 && echo "test: $$n test files checked"

vuln: ## pip-audit over the locked runtime dependencies
	@command -v $(UV) >/dev/null || $(call skip,vuln,uv); command -v uvx >/dev/null || $(call skip,vuln,uvx); \
	[ -f uv.lock ] || { echo "vuln: no uv.lock; run make setup and commit it" >&2; exit 1; }; \
	n=$$($(UV) export --frozen --no-dev --no-hashes --no-emit-project | grep -c '==' || true); \
	[ "$$n" -gt 0 ] || { echo "vuln: 0 packages, nothing checked" >&2; exit 1; }; \
	uvx pip-audit --strict --no-deps -r <($(UV) export --frozen --no-dev --no-hashes --no-emit-project) && echo "vuln: $$n packages checked"

check: ## The gate: every gate in GATES, then the tally. CI runs exactly this.
	@mkdir -p $(STATE); rm -f $(SKIPPED) $(STATE)/.check-passed
	@for g in $(GATES); do $(MAKE) --no-print-directory $$g || { echo "check: $$g failed" >&2; exit 1; }; done
	@s=$$(cut -d' ' -f1 $(SKIPPED) 2>/dev/null | sort -u | wc -l | tr -d ' '); r=$$(( $(words $(GATES)) - s )); \
	echo "check: $$r gates run, $$s skipped"; \
	if [ "$$s" -eq 0 ]; then touch $(STATE)/.check-passed; echo "check: passed"; \
	elif [ "$${BEARING_ALLOW_SKIP:-0}" = "1" ] && [ -z "$$CI" ]; then sed 's/^/  skipped: /' $(SKIPPED); echo "check: passed with skips (BEARING_ALLOW_SKIP=1 is a local convenience; CI never sets it)"; \
	else sed 's/^/  skipped: /' $(SKIPPED); echo "check: FAILED, $$s gate(s) skipped; run make setup, or BEARING_ALLOW_SKIP=1 make check locally" >&2; exit 1; fi

check-file: ## Lint one edited file, FILE=path (the Bearing edit hook runs this)
	@[ -n "$(FILE)" ] || { echo "check-file: FILE is empty, nothing checked" >&2; exit 1; }; \
	[ -f "$(FILE)" ] || { echo "check-file: $(FILE) does not exist, nothing checked" >&2; exit 1; }; \
	case "$(FILE)" in \
	  *.py) command -v $(UV) >/dev/null || { echo "check-file: uv not installed, $(FILE) not checked"; exit 0; }; $(UV) run ruff check --quiet --force-exclude "$(FILE)" || exit 1;; \
	  *) echo "check-file: no per-file check for $(FILE)"; exit 0;; \
	esac; \
	echo "check-file: 1 file checked"

fix: format ## Apply every automatic fix
	@$(UV) run ruff check --fix . || true

doctor: ## Environment diagnostics
	@echo "uv:        $$(command -v $(UV) >/dev/null && $(UV) --version || echo missing)"
	@echo "python:    $$($(UV) run python --version 2>/dev/null || echo 'missing (run make setup)')"
	@echo "ruff:      $$($(UV) run --quiet ruff --version 2>/dev/null || echo missing)"
	@echo "mypy:      $$($(UV) run --quiet mypy --version 2>/dev/null || echo missing)"
	@echo "docker:    $$(command -v docker >/dev/null && docker --version || echo missing)"
	@echo "lock:      $$([ -f uv.lock ] && echo present || echo 'MISSING (run make setup and commit uv.lock)')"
	@echo "hooksPath: $$(git config core.hooksPath || echo 'NOT SET (run make setup)')"

clean: ## Remove caches and build output
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov dist build $(STATE)/.check-passed $(SKIPPED)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
