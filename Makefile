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
