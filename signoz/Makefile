SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Config ────────────────────────────────────────────────────────────────
ROOT_DIR      := $(abspath $(CURDIR)/../..)
CASTING_FILE  ?= $(ROOT_DIR)/casting.yaml
COMPOSE_FILE  ?= stack/compose.yaml

# Two equivalent ways to run SigNoz (see observability/signoz/README.md):
#   1. `docker compose -f stack/compose.yaml` — committed snapshot, no foundryctl needed.
#      This is what up/down/restart/status/logs/ps use below.
#   2. `foundryctl cast -f casting.yaml` — regenerates the snapshot from source. Only needed
#      when casting.yaml changes; see the `forge`/`cast` targets.
DOCKER_COMPOSE := docker compose -f $(COMPOSE_FILE)
FOUNDRYCTL     ?= foundryctl

SIGNOZ_URL    ?= http://localhost:8080
SIGNOZ_API_TOKEN ?=

DASHBOARD_FILE := dashboards/agentdrops-agent.json
ALERTS_DIR     := alerts

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

.PHONY: help doctor up down restart status ps logs open forge cast \
        import-dashboard import-alerts import-all

help: ## Show this help
	@printf "$(BOLD)SigNoz — make targets$(RESET)\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / { printf "  $(CYAN)%-16s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n$(DIM)UI: $(SIGNOZ_URL)   OTLP gRPC :4317   OTLP HTTP :4318   MCP :8000$(RESET)\n"
	@printf "$(DIM)First run: open $(SIGNOZ_URL) and create the admin account, or OTLP stays down.$(RESET)\n"
	@printf "$(DIM)Set SIGNOZ_API_TOKEN for import-* targets.$(RESET)\n"

doctor: ## Sanity-check compose file, docker, and (optionally) foundryctl
	@$(call banner,Environment check)
	@[ -f "$(COMPOSE_FILE)" ] \
		&& $(call log_ok,compose stack found at $(COMPOSE_FILE)) \
		|| $(call log_err,compose stack missing at $(COMPOSE_FILE))
	@docker info >/dev/null 2>&1 \
		&& $(call log_ok,docker daemon reachable) \
		|| $(call log_warn,docker not reachable — up/down will fail)
	@command -v $(FOUNDRYCTL) >/dev/null 2>&1 \
		&& $(call log_ok,foundryctl found: $$(command -v $(FOUNDRYCTL)) (only needed for \`make forge\`)) \
		|| $(call log_info,foundryctl not on PATH — fine unless you need \`make forge\`)

up: doctor ## Start SigNoz (docker compose -f stack/compose.yaml up -d)
	@$(call banner,Starting SigNoz)
	@$(DOCKER_COMPOSE) up -d \
		&& $(call log_ok,SigNoz is up) \
		&& $(call log_info,UI:        $(SIGNOZ_URL)) \
		&& $(call log_info,OTLP gRPC: http://localhost:4317) \
		&& $(call log_info,OTLP HTTP: http://localhost:4318) \
		&& $(call log_info,MCP:       http://localhost:8000) \
		&& $(call log_warn,first run only: open $(SIGNOZ_URL) and create the admin account) \
		|| ($(call log_err,docker compose up failed — check output above); exit 1)
	@$(DOCKER_COMPOSE) ps

down: ## Stop SigNoz (keeps volumes)
	@$(call banner,Stopping SigNoz)
	@$(DOCKER_COMPOSE) down && $(call log_ok,SigNoz stopped) || ($(call log_err,teardown failed); exit 1)

restart: down up ## Stop and restart SigNoz

status: ps ## Alias for `ps`

ps: ## Show SigNoz container status
	@$(DOCKER_COMPOSE) ps

logs: ## Tail SigNoz container logs
	@$(DOCKER_COMPOSE) logs -f

open: ## Open the SigNoz UI in the default browser
	@$(call log_info,Opening $(SIGNOZ_URL))
	@open "$(SIGNOZ_URL)"

forge: ## Regenerate stack/compose.yaml from casting.yaml (requires foundryctl)
	@$(call banner,Regenerating stack snapshot from $(CASTING_FILE))
	@command -v $(FOUNDRYCTL) >/dev/null 2>&1 || { $(call log_err,foundryctl not on PATH); exit 1; }
	@$(FOUNDRYCTL) forge -f $(CASTING_FILE) \
		&& $(call log_ok,stack snapshot regenerated — review the diff before committing) \
		|| ($(call log_err,forge failed); exit 1)

cast: ## Deploy SigNoz straight from casting.yaml via foundryctl (source of truth, no snapshot)
	@$(call banner,Deploying via foundryctl cast)
	@command -v $(FOUNDRYCTL) >/dev/null 2>&1 || { $(call log_err,foundryctl not on PATH); exit 1; }
	@$(FOUNDRYCTL) cast -f $(CASTING_FILE) \
		&& $(call log_ok,SigNoz deployed via foundryctl) \
		|| ($(call log_err,cast failed); exit 1)

import-dashboard: ## POST dashboards/agentdrops-agent.json to SigNoz (needs SIGNOZ_API_TOKEN)
	@$(call banner,Importing dashboard)
	@if [ -z "$(SIGNOZ_API_TOKEN)" ]; then $(call log_err,SIGNOZ_API_TOKEN is not set); exit 1; fi
	@curl -sf -X POST "$(SIGNOZ_URL)/api/v1/dashboards" \
		-H "Authorization: Bearer $(SIGNOZ_API_TOKEN)" \
		-H "Content-Type: application/json" \
		--data @$(DASHBOARD_FILE) >/dev/null \
		&& $(call log_ok,imported $(DASHBOARD_FILE)) \
		|| ($(call log_err,dashboard import failed); exit 1)

import-alerts: ## POST every alerts/*.json rule to SigNoz (needs SIGNOZ_API_TOKEN)
	@$(call banner,Importing alert rules)
	@if [ -z "$(SIGNOZ_API_TOKEN)" ]; then $(call log_err,SIGNOZ_API_TOKEN is not set); exit 1; fi
	@for f in $(ALERTS_DIR)/*.json; do \
		curl -sf -X POST "$(SIGNOZ_URL)/api/v2/rules" \
			-H "Authorization: Bearer $(SIGNOZ_API_TOKEN)" \
			-H "Content-Type: application/json" \
			--data @$$f >/dev/null \
			&& $(call log_ok,imported $$f) \
			|| { $(call log_err,failed to import $$f); exit 1; }; \
	done
	@$(call log_warn,alerts reference the 'agentdrops-webhook' notification channel — create it first if missing)

import-all: import-dashboard import-alerts ## Import dashboard + alerts in one shot
	@$(call log_ok,all SigNoz assets imported)
