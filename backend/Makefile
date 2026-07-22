SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Config (override on the command line, e.g. `make run PORT=8080`) ────────
VENV        ?= .venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
# `python -m pytest`, not the `pytest` console script directly: the script entry point doesn't
# add cwd to sys.path, so `from tests.unit... import ...` fails to resolve the `tests` package.
PYTEST      := $(PYTHON) -m pytest
RUFF        := $(VENV)/bin/ruff
MYPY        := $(VENV)/bin/mypy

APP         := agentdrops.main:app
HOST        ?= 0.0.0.0
# Port 8001, not 8000: SigNoz's MCP server owns 8000 (see casting.yaml / frontend/src/lib/api.ts).
PORT        ?= 8001
LOG_LEVEL   ?= info

# ── Colors (disable with NO_COLOR=1) ─────────────────────────────────────────
ifndef NO_COLOR
  BOLD    := \033[1m
  DIM     := \033[2m
  RED     := \033[0;31m
  GREEN   := \033[0;32m
  YELLOW  := \033[0;33m
  BLUE    := \033[0;34m
  MAGENTA := \033[0;35m
  CYAN    := \033[0;36m
  RESET   := \033[0m
endif

define log_info
printf "$(CYAN)[%s]$(RESET) $(BOLD)INFO $(RESET) %s\n" "$$(date '+%H:%M:%S')" "$(1)"
endef
define log_ok
printf "$(GREEN)[%s]$(RESET) $(BOLD)OK   $(RESET) %s\n" "$$(date '+%H:%M:%S')" "$(1)"
endef
define log_warn
printf "$(YELLOW)[%s]$(RESET) $(BOLD)WARN $(RESET) %s\n" "$$(date '+%H:%M:%S')" "$(1)"
endef
define log_err
printf "$(RED)[%s]$(RESET) $(BOLD)ERROR$(RESET) %s\n" "$$(date '+%H:%M:%S')" "$(1)" >&2
endef
define banner
printf "\n$(MAGENTA)$(BOLD)==> %s$(RESET)\n" "$(1)"
endef

.PHONY: help venv install env infra-up infra-down infra-restart infra-ps infra-logs infra-reset \
        run dev stop test test-file lint lint-fix format typecheck check clean doctor

help: ## Show this help
	@printf "$(BOLD)Agentdrops backend — make targets$(RESET)\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / { printf "  $(CYAN)%-14s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n$(DIM)Override vars inline, e.g. \`make run PORT=8080 LOG_LEVEL=debug\`$(RESET)\n"

venv: ## Create the virtualenv (.venv) if it doesn't exist
	@if [ ! -x "$(PYTHON)" ]; then \
		$(call log_info,Creating virtualenv at $(VENV)); \
		python3 -m venv $(VENV) && $(call log_ok,virtualenv ready); \
	else \
		$(call log_info,virtualenv already present at $(VENV)); \
	fi

install: venv ## Install backend deps (editable, dev extras)
	@$(call banner,Installing agentdrops[dev])
	@$(PIP) install -e ".[dev]" \
		&& $(call log_ok,dependencies installed) \
		|| ($(call log_err,pip install failed); exit 1)

env: ## Copy .env.example to .env if missing
	@if [ -f .env ]; then \
		$(call log_warn,.env already exists — leaving it untouched); \
	else \
		cp .env.example .env && $(call log_ok,.env created from .env.example — fill in the required keys); \
	fi

infra-up: ## Start postgres/redis/minio via docker compose
	@$(call banner,Starting infra: postgres redis minio)
	@docker compose up -d \
		&& $(call log_ok,infra containers up) \
		|| ($(call log_err,docker compose up failed); exit 1)
	@docker compose ps

infra-down: ## Stop infra containers (keeps volumes)
	@$(call banner,Stopping infra)
	@docker compose down && $(call log_ok,infra stopped)

infra-restart: infra-down infra-up ## Restart infra containers

infra-reset: ## Stop infra and wipe volumes — destroys local postgres/redis/minio data
	@$(call log_warn,This deletes local postgres/redis/minio data)
	@docker compose down -v && $(call log_ok,infra stopped and volumes removed)

infra-ps: ## Show infra container status
	@docker compose ps

infra-logs: ## Tail infra container logs
	@docker compose logs -f

run: infra-up ## Start the FastAPI backend (uvicorn --reload) on $(PORT)
	@$(call banner,Starting Agentdrops backend)
	@$(call log_info,host=$(HOST) port=$(PORT) reload=on log-level=$(LOG_LEVEL))
	@$(call log_info,python=$$($(PYTHON) --version 2>&1) git=$$(git rev-parse --short HEAD 2>/dev/null || echo n/a))
	@if [ -f .env ]; then \
		provider=$$(grep -m1 '^LLM_PROVIDER=' .env | cut -d= -f2); \
		otel=$$(grep -m1 '^OTEL_ENABLED=' .env | cut -d= -f2); \
		$(call log_info,llm_provider=$${provider:-unset} otel_enabled=$${otel:-unset}); \
	else \
		$(call log_warn,.env not found — run \`make env\` first (Settings will fail fast without it)); \
	fi
	@$(call log_info,docs at http://localhost:$(PORT)/docs)
	@$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --reload --log-level $(LOG_LEVEL) \
		|| ($(call log_err,backend server exited non-zero); exit 1)

dev: run ## Alias for `run`

stop: ## Kill whatever is listening on $(PORT)
	@pid=$$(lsof -ti tcp:$(PORT)); \
	if [ -n "$$pid" ]; then \
		kill $$pid && $(call log_ok,killed process $$pid on port $(PORT)); \
	else \
		$(call log_warn,nothing listening on port $(PORT)); \
	fi

test: ## Run the pytest suite
	@$(call banner,Running tests)
	@$(PYTEST) && $(call log_ok,tests passed) || ($(call log_err,tests failed); exit 1)

test-file: ## Run one test: make test-file FILE=tests/unit/... [-k name]
	@$(call banner,Running $(FILE))
	@$(PYTEST) $(FILE) && $(call log_ok,tests passed) || ($(call log_err,tests failed); exit 1)

lint: ## Run ruff checks
	@$(call banner,Linting (ruff check))
	@$(RUFF) check . && $(call log_ok,lint passed) || ($(call log_err,lint failed); exit 1)

lint-fix: ## Run ruff checks with autofix
	@$(call banner,Linting (ruff check --fix))
	@$(RUFF) check . --fix && $(call log_ok,lint passed) || ($(call log_err,lint failed); exit 1)

format: ## Run ruff format
	@$(call banner,Formatting (ruff format))
	@$(RUFF) format . && $(call log_ok,format complete)

typecheck: ## Run mypy in strict mode
	@$(call banner,Typechecking (mypy src))
	@$(MYPY) src && $(call log_ok,typecheck passed) || ($(call log_err,typecheck failed); exit 1)

check: lint typecheck test ## Run lint + typecheck + test (what CI runs)
	@$(call log_ok,all checks passed)

clean: ## Remove caches and build artifacts
	@$(call banner,Cleaning caches)
	@rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build \
		&& find . -type d -name '__pycache__' -not -path './.venv/*' -prune -exec rm -rf {} + \
		&& $(call log_ok,workspace cleaned)

doctor: ## Sanity-check local dev environment
	@$(call banner,Environment check)
	@[ -x "$(PYTHON)" ] && $(call log_ok,venv present) || $(call log_warn,no venv — run \`make venv\`)
	@[ -f .env ] && $(call log_ok,.env present) || $(call log_warn,no .env — run \`make env\`)
	@docker info >/dev/null 2>&1 && $(call log_ok,docker daemon reachable) || $(call log_warn,docker not reachable — infra targets will fail)
	@command -v lsof >/dev/null 2>&1 && $(call log_ok,lsof available (needed by \`make stop\`)) || $(call log_warn,lsof not found)
