SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Config (override on the command line, e.g. `make dev PORT=3001`) ────────
NPM         := npm
NPX         := npx
PORT        ?= 3000
API_BASE_URL ?= http://localhost:8001

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

.PHONY: help install dev run build start lint lint-fix typecheck check clean stop doctor

help: ## Show this help
	@printf "$(BOLD)Agentdrops frontend — make targets$(RESET)\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / { printf "  $(CYAN)%-14s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n$(DIM)Override vars inline, e.g. \`make dev PORT=3001\`$(RESET)\n"

install: ## Install frontend deps
	@$(call banner,Installing frontend dependencies)
	@$(NPM) install \
		&& $(call log_ok,dependencies installed) \
		|| ($(call log_err,npm install failed); exit 1)

dev: ## Start the Next.js dev server on $(PORT) (backend must be running on $(API_BASE_URL))
	@$(call banner,Starting Agentdrops frontend (dev))
	@$(call log_info,port=$(PORT) api_base_url=$(API_BASE_URL))
	@$(call log_warn,CORS on the backend is pinned to :3000 — running on another port will break API calls)
	@NEXT_PUBLIC_API_BASE_URL=$(API_BASE_URL) $(NPM) run dev -- --port $(PORT) \
		|| ($(call log_err,dev server exited non-zero); exit 1)

run: dev ## Alias for `dev`

build: ## Build the production bundle (bakes $(API_BASE_URL) into the client bundle)
	@$(call banner,Building frontend)
	@NEXT_PUBLIC_API_BASE_URL=$(API_BASE_URL) $(NPM) run build \
		&& $(call log_ok,build complete) \
		|| ($(call log_err,build failed); exit 1)

start: build ## Build and start the production server on $(PORT)
	@$(call banner,Starting Agentdrops frontend (production))
	@$(NPM) run start -- --port $(PORT) \
		|| ($(call log_err,production server exited non-zero); exit 1)

lint: ## Run eslint
	@$(call banner,Linting (eslint))
	@$(NPM) run lint && $(call log_ok,lint passed) || ($(call log_err,lint failed); exit 1)

lint-fix: ## Run eslint with autofix
	@$(call banner,Linting (eslint --fix))
	@$(NPM) run lint -- --fix && $(call log_ok,lint passed) || ($(call log_err,lint failed); exit 1)

typecheck: ## Run the TypeScript compiler in no-emit mode
	@$(call banner,Typechecking (tsc --noEmit))
	@$(NPX) tsc --noEmit && $(call log_ok,typecheck passed) || ($(call log_err,typecheck failed); exit 1)

check: lint typecheck build ## Run lint + typecheck + build (what CI runs)
	@$(call log_ok,all checks passed)

clean: ## Remove build artifacts and caches
	@$(call banner,Cleaning caches)
	@rm -rf .next out node_modules/.cache \
		&& $(call log_ok,workspace cleaned)

stop: ## Kill whatever is listening on $(PORT)
	@command -v lsof >/dev/null 2>&1 || ($(call log_err,lsof not found — cannot query port $(PORT)); exit 1)
	@pid=$$(lsof -ti tcp:$(PORT)); \
	if [ -n "$$pid" ]; then \
		kill $$pid && $(call log_ok,killed process $$pid on port $(PORT)); \
	else \
		$(call log_warn,nothing listening on port $(PORT)); \
	fi

doctor: ## Sanity-check local dev environment
	@$(call banner,Environment check)
	@[ -d node_modules ] && $(call log_ok,node_modules present) || $(call log_warn,no node_modules — run \`make install\`)
	@status=0; \
	command -v node >/dev/null 2>&1 && $(call log_ok,node $$(node --version)) || { $(call log_err,node not found); status=1; }; \
	command -v npm >/dev/null 2>&1 && $(call log_ok,npm $$(npm --version)) || { $(call log_err,npm not found); status=1; }; \
	command -v lsof >/dev/null 2>&1 && $(call log_ok,lsof available (needed by \`make stop\`)) || $(call log_warn,lsof not found); \
	exit $$status
