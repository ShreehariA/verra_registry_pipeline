# Verra registry pipeline. Run `make` to list the commands.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup check build query dashboard clean

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

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

dashboard: ## Serve the dashboard on the newest build at http://localhost:8501
	@echo "Dashboard: http://localhost:8501 (Ctrl+C stops it)"
	$(UV) run streamlit run dashboard/app.py

clean: ## Delete everything the pipeline generated (lake/); never touches data/landing
	rm -rf lake
