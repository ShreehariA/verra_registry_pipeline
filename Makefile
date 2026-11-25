# Verra registry pipeline. Run `make` to list the commands.
.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup check lint types test build query dashboard analysis clean

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Create .venv with the locked dependencies (needs uv)
	$(UV) sync

check: lint types test ## Lint, type-check and test: run before every commit

lint: ## Check style and formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

types: ## Check the pipeline's types
	$(UV) run mypy

test: ## Run the tests
	$(UV) run pytest

build: ## Build every layer from the newest complete snapshot in data/landing, or SNAPSHOT=YYYY-MM-DD
	$(UV) run verra build $(if $(SNAPSHOT),--snapshot $(SNAPSHOT))

query: ## Run SQL, e.g. make query SQL="select count(*) from bronze.retirements"
	$(UV) run verra query "$(SQL)"

dashboard: ## Serve the dashboard on the newest build at http://localhost:8501
	@echo "Dashboard: http://localhost:8501 (Ctrl+C stops it)"
	$(UV) run streamlit run dashboard/app.py

analysis: ## Print the data analysis behind docs/data-analysis.md (reads data/landing; writes nothing)
	@for script in files columns dates vintages serials owners projects reasons totals; do \
		$(UV) run python analysis/$$script.py || exit 1; \
	done

clean: ## Delete everything the pipeline generated (lake/); never touches data/landing
	rm -rf lake
