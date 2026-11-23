# Verra registry pipeline. Run `make` to list the commands.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup check build query clean

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-8s %s\n", $$1, $$2}'

setup: ## Create .venv with the locked dependencies (needs uv)
	$(UV) sync

check: ## Lint, type-check and test: run before every commit
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy
	$(UV) run pytest

build: ## Build every layer from the newest complete snapshot in data/landing
	$(UV) run verra build

query: ## Run SQL, e.g. make query SQL="select count(*) from bronze.retirements"
	$(UV) run verra query "$(SQL)"

clean: ## Delete everything the pipeline generated (lake/); never touches data/landing
	rm -rf lake
