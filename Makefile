.PHONY: install
install: ## Install the virtual environment and install the pre-commit hooks
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: run
run: ##
	@echo "🚀 Run local server."
	@uv run uvicorn compose_api.api.main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: check
check: ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a
	@echo "🚀 Static type checking: Running mypy"
	@uv run mypy
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@uv run deptry .
	@$(MAKE) --no-print-directory check-clients

.PHONY: clients
clients: ## Regenerate the OpenAPI spec and the Python client from the app (LIB_DIR=... also writes the external repo)
	@echo "🚀 Generating OpenAPI Spec"
	@uv run python compose_api/api/openapi_spec.py
	@echo "🚀 Creating HTTPX Clients"
	@scripts/generate-api-client.sh
	@if [ -d webapp/node_modules ]; then echo "🚀 Regenerating the web UI's API types"; cd webapp && npm run --silent types; \
	else echo "⚠️  webapp/node_modules missing: run 'make webapp-install' to regenerate webapp/app/api/schema.d.ts"; fi

.PHONY: cli-docs
cli-docs: ## Regenerate the command reference at the end of docs/cli.md
	@scripts/cli-docs.sh docs/cli.md

.PHONY: check-clients
check-clients: ## Fail if the committed spec or client differs from a fresh generation (docs/plan-cli.md, step A)
	@echo "🚀 Checking the OpenAPI spec and the generated client are current"
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	uv run python compose_api/api/openapi_spec.py "$$tmp/spec.yaml" >/dev/null && \
	diff -u compose_api/api/spec/openapi_3_1_0_generated.yaml "$$tmp/spec.yaml" && \
	scripts/generate-api-client.sh "$$tmp/client" >/dev/null && \
	diff -r -x __pycache__ -x utils -x ext -x cli clients/python/compose_api_client "$$tmp/client" && \
	cp docs/cli.md "$$tmp/cli.md" && scripts/cli-docs.sh "$$tmp/cli.md" && diff -u docs/cli.md "$$tmp/cli.md" || \
	{ echo "❌ The spec, the client or the CLI reference is stale: run 'make clients cli-docs' and commit."; exit 1; }

.PHONY: webapp-install
webapp-install: ## Install the web UI's npm dependencies (webapp/, Node 24)
	@cd webapp && npm ci

.PHONY: webapp-dev
webapp-dev: ## Serve the web UI on http://localhost:4200/ui/ against `make run` (COMPOSE_API_URL=... for another API)
	@cd webapp && NUXT_PUBLIC_API_BASE=$${COMPOSE_API_URL:-http://localhost:8000} npm run dev

.PHONY: webapp-build
webapp-build: ## Build the static web UI into webapp/.output/public, which `make run` then serves at /ui
	@cd webapp && npm run generate

.PHONY: webapp-check
webapp-check: ## Lint and typecheck the web UI, and fail if its API types are stale
	@cd webapp && npm run --silent types && git diff --exit-code app/api/schema.d.ts && npm run lint && npm run typecheck

.PHONY: test
test: ## Test the code with pytest
	@echo "🚀 Testing code: Running pytest"
	@uv run python -m pytest --cov --cov-config=pyproject.toml --cov-report=xml

.PHONY: build
build: clean-build ## Build wheel file
	@echo "🚀 Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: tag
tag:
	@echo "🚀 Setting Version of ComposeAPI"
	@./tag.sh


.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	@uv run mkdocs build -s

.PHONY: docs
docs: ## Build and serve the documentation
	@uv run mkdocs serve

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.PHONY: db-migrate
db-migrate: ## Auto-generate migration from model changes (usage: make db-migrate msg="description")
	@test -n "$(msg)" || (echo "Usage: make db-migrate msg=\"your message\"" && exit 1)
	@echo "🚀 Generating migration: $(msg)"
	@uv run alembic revision --autogenerate -m "$(msg)"

.PHONY: db-upgrade
db-upgrade: ## Apply all pending migrations to the database
	@echo "🚀 Applying migrations"
	@uv run alembic upgrade head

.PHONY: db-stamp
db-stamp: ## Mark existing database as current without running migrations
	@echo "🚀 Stamping database as current head"
	@uv run alembic stamp head

.PHONY: deploy
deploy: ## Deploy to site
	@echo "🚀 Deploying ComposeAPI to Site"
	@kubectl kustomize kustomize/overlays/compose-api-rke | kubectl apply -f -


.DEFAULT_GOAL := help
