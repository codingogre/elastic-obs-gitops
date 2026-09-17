# Everyday commands. Credentials come from scripts/with_env.py (local .env files or CI secrets).
ENV ?= dev
PY  ?= python3
RUN  = $(PY) scripts/with_env.py $(ENV) --
TF   = terraform -chdir=envs/$(ENV)

.PHONY: help init plan apply fmt fmt-check validate platform-init platform-plan

help:
	@echo "make init|plan ENV=dev|prod   make apply ENV=dev   make fmt   make validate"
	@echo "make platform-init|platform-plan"
	@echo "make demo-act1|demo-act2|demo-act3 [PAUSE=1] [STEP=<beat>] [DRY_RUN=1]   make demo-reset [DRY_RUN=1]"

init:
	$(PY) scripts/with_env.py $(ENV) --backend -- $(TF) init -input=false

plan:
	$(RUN) $(TF) plan -input=false

apply:
	@if [ "$(ENV)" = "prod" ]; then echo "Refusing: prod is applied only by the apply-prod GitHub Actions job."; exit 1; fi
	$(RUN) $(TF) apply -input=false

fmt:
	terraform fmt -recursive

fmt-check:
	terraform fmt -recursive -check

validate:
	$(RUN) $(TF) validate

platform-init:
	$(PY) scripts/with_env.py platform --backend -- terraform -chdir=platform init -input=false

platform-plan:
	$(PY) scripts/with_env.py platform -- terraform -chdir=platform plan -input=false

# ── Pipeline helpers (all read credentials through scripts/with_env.py) ───────
VENV_PY ?= .venv/bin/python
SERVICE ?= grid-dispatch
VERSION ?= 2.4.3
BASELINE ?=
MODE ?= app
ERROR_RATE ?= 0.005
DEGRADE_AFTER ?= 0
TYPE ?= apply
STATUS ?= success
TITLE ?=
ID ?=

.PHONY: venv traffic gate event capture demo-preflight

venv:
	python3 -m venv .venv && $(VENV_PY) -m pip install -q -r scripts/requirements.txt

traffic:
	$(RUN) $(VENV_PY) scripts/traffic.py --env $(ENV) --service $(SERVICE) --version $(VERSION) \
	  --error-rate $(ERROR_RATE) $(if $(filter-out 0,$(DEGRADE_AFTER)),--degrade-after $(DEGRADE_AFTER))

gate:
	$(RUN) python3 scripts/gate.py --service $(SERVICE) --version $(VERSION) --baseline "$(BASELINE)" --mode $(MODE) --environment $(ENV)

event:
	$(RUN) python3 scripts/emit_event.py --action $(TYPE) --env $(ENV) --outcome $(STATUS)

capture:
	@if [ "$(ENV)" != "dev" ]; then echo "Capture works on dev only."; exit 1; fi
	$(RUN) python3 scripts/capture.py --no-pr $(if $(ID),--object-id "$(ID)",--object-title "$(TITLE)")

demo-preflight:
	$(RUN) python3 scripts/preflight_connectors.py --env $(ENV)

# ── Live acts and reset (drivers load both environments' credentials themselves; they print every link) ──
# PAUSE=1 waits for Enter between beats, STEP=<beat> runs one beat, SKIP=a,b leaves beats out, DRY_RUN=1 changes nothing.
PAUSE ?=
STEP ?=
SKIP ?=
DRY_RUN ?=
DEMO_FLAGS = $(if $(filter-out 0,$(PAUSE)),--pause) $(if $(STEP),--step $(STEP)) $(if $(SKIP),--skip $(SKIP)) \
  $(if $(filter-out 0,$(DRY_RUN)),--dry-run)
RELEASE_FLAGS = $(if $(filter-out 0,$(DEGRADE_AFTER)),--degrade-after $(DEGRADE_AFTER))

.PHONY: demo-act1 demo-act2 demo-act3 demo-reset

demo-act1:
	$(PY) scripts/demo_act1.py $(DEMO_FLAGS)

demo-act2:
	$(PY) scripts/demo_act2.py $(DEMO_FLAGS) $(RELEASE_FLAGS)

demo-act3:
	$(PY) scripts/demo_act3.py $(DEMO_FLAGS) $(RELEASE_FLAGS)

demo-reset:
	$(PY) scripts/demo_reset.py $(DEMO_FLAGS)

# ── elasticgitops provider, built from source into a filesystem mirror (DECISIONS ADR-002) ──
PROVIDER_SRC ?= ../terraform-provider-elasticgitops
PROVIDER_VERSION ?= 0.1.0
GO ?= $(shell test -x /opt/homebrew/bin/go && echo /opt/homebrew/bin/go || echo go)

.PHONY: provider
provider:
	cd $(PROVIDER_SRC) && PATH="$(dir $(GO)):$$PATH" ./scripts/build-mirror.sh "$(CURDIR)/.provider-mirror" $(PROVIDER_VERSION)
	printf 'provider_installation {\n  filesystem_mirror {\n    path    = "%s"\n    include = ["registry.terraform.io/codingogre/elasticgitops"]\n  }\n  direct {\n    exclude = ["registry.terraform.io/codingogre/elasticgitops"]\n  }\n}\n' "$(CURDIR)/.provider-mirror" > .provider-mirror/terraformrc
	@echo "Built codingogre/elasticgitops $(PROVIDER_VERSION) into .provider-mirror"
