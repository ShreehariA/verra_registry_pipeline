# Verra registry pipeline: the commands you need. Run `make` to list them.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup test lint format typecheck check ingest query clean

help: ## List the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Create .venv and install the pinned dependencies (needs uv)
	$(UV) sync

test: ## Run every test
	$(UV) run pytest

lint: ## Check code style and formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Fix code formatting in place
	$(UV) run ruff format .

typecheck: ## Check the type hints
	$(UV) run mypy

check: lint typecheck test ## Lint, type-check and test: run before every commit

ingest: ## Step 1: load the newest complete snapshot in data/landing into bronze
	$(UV) run verra ingest

query: ## Run SQL against the lake, e.g. make query SQL="select count(*) from bronze.retirements"
	$(UV) run verra query "$(SQL)"

clean: ## Delete everything the pipeline generated (lake/, warehouse/); never touches data/landing
	rm -rf lake warehouse
