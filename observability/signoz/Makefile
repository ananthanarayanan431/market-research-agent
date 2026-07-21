SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Config ────────────────────────────────────────────────────────────────
ROOT_DIR      := $(abspath $(CURDIR)/../..)
CASTING_FILE  ?= $(ROOT_DIR)/casting.yaml

# `foundryctl cast` is the only command this repo's docs mention (observability/signoz/README.md)
# — no subcommand reference is checked in, so these are best-guess verbs. Override on the
# command line if your installed foundryctl differs, e.g.:
#   make up CAST_UP="foundryctl cast apply -f $(CASTING_FILE)"
FOUNDRYCTL    ?= foundryctl
CAST_UP       ?= $(FOUNDRYCTL) cast -f $(CASTING_FILE) up
CAST_DOWN     ?= $(FOUNDRYCTL) cast -f $(CASTING_FILE) down
CAST_STATUS   ?= $(FOUNDRYCTL) cast -f $(CASTING_FILE) status
CAST_LOGS     ?= $(FOUNDRYCTL) cast -f $(CASTING_FILE) logs

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

.PHONY: help doctor up down restart status logs open \
        import-dashboard import-alerts import-all

help: ## Show this help
	@printf "$(BOLD)SigNoz — make targets$(RESET)\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / { printf "  $(CYAN)%-16s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n$(DIM)UI: $(SIGNOZ_URL)   OTLP gRPC :4317   OTLP HTTP :4318   MCP :8000$(RESET)\n"
	@printf "$(DIM)Set SIGNOZ_API_TOKEN for import-* targets.$(RESET)\n"

doctor: ## Sanity-check foundryctl, casting.yaml, and docker
	@$(call banner,Environment check)
	@command -v $(FOUNDRYCTL) >/dev/null 2>&1 \
		&& $(call log_ok,foundryctl found: $$(command -v $(FOUNDRYCTL))) \
		|| $(call log_warn,foundryctl not on PATH — install it before running \`make up\`)
	@[ -f "$(CASTING_FILE)" ] \
		&& $(call log_ok,casting.yaml found at $(CASTING_FILE)) \
		|| $(call log_err,casting.yaml missing at $(CASTING_FILE))
	@docker info >/dev/null 2>&1 \
		&& $(call log_ok,docker daemon reachable (casting.yaml uses flavor: compose)) \
		|| $(call log_warn,docker not reachable — SigNoz deploy will fail)

up: doctor ## Deploy SigNoz via foundryctl cast (casting.yaml)
	@$(call banner,Deploying SigNoz)
	@$(call log_info,$(CAST_UP))
	@$(CAST_UP) \
		&& $(call log_ok,SigNoz is up) \
		&& $(call log_info,UI:        $(SIGNOZ_URL)) \
		&& $(call log_info,OTLP gRPC: http://localhost:4317) \
		&& $(call log_info,OTLP HTTP: http://localhost:4318) \
		&& $(call log_info,MCP:       http://localhost:8000) \
		|| ($(call log_err,SigNoz deploy failed — check foundryctl output above); exit 1)

down: ## Tear down the SigNoz deployment
	@$(call banner,Tearing down SigNoz)
	@$(call log_info,$(CAST_DOWN))
	@$(CAST_DOWN) && $(call log_ok,SigNoz stopped) || ($(call log_err,teardown failed); exit 1)

restart: down up ## Tear down and redeploy SigNoz

status: ## Show SigNoz deployment status
	@$(call log_info,$(CAST_STATUS))
	@$(CAST_STATUS)

logs: ## Tail SigNoz deployment logs
	@$(call log_info,$(CAST_LOGS))
	@$(CAST_LOGS)

open: ## Open the SigNoz UI in the default browser
	@$(call log_info,Opening $(SIGNOZ_URL))
	@open "$(SIGNOZ_URL)"

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
