# Everyday commands. Credentials come from scripts/with_env.py (local .env files or CI secrets).
ENV ?= dev
PY  ?= python3
RUN  = $(PY) scripts/with_env.py $(ENV) --
TF   = terraform -chdir=envs/$(ENV)

.PHONY: help init plan apply fmt fmt-check validate platform-init platform-plan

help:
	@echo "make init|plan ENV=dev|prod   make apply ENV=dev   make fmt   make validate"
	@echo "make platform-init|platform-plan"

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
