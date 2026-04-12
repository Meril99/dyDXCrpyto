# =============================================================================
# Makefile — dYdX Market Making Bot
# Convenience targets for development, testing, and deployment.
# =============================================================================

.PHONY: help build run stop logs test lint typecheck cpp clean deploy

DOCKER_IMAGE  := dydx-bot
COMPOSE       := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Docker ──────────────────────────────────────────────────────────────────

build: ## Build Docker image (multi-stage with C++ order book)
	$(COMPOSE) build

run: ## Start the bot (detached)
	$(COMPOSE) up -d bot

stop: ## Stop all services
	$(COMPOSE) down

logs: ## Follow bot logs
	$(COMPOSE) logs -f bot

ps: ## Show running services
	$(COMPOSE) ps

# ── Development ─────────────────────────────────────────────────────────────

test: ## Run unit tests
	pytest tests/ -v --tb=short

lint: ## Run flake8 linter
	flake8 dydx3/ quant/ --max-line-length=100 --statistics

typecheck: ## Run mypy type checker
	mypy dydx3/ --ignore-missing-imports

cpp: ## Build C++ order book module
	cd cpp && chmod +x build.sh && ./build.sh

# ── Testing with Ganache ────────────────────────────────────────────────────

test-integration: ## Run integration tests with local Ganache
	$(COMPOSE) --profile test up -d ganache
	sleep 3
	V3_API_HOST=http://localhost:8545 pytest integration_tests/ -v
	$(COMPOSE) --profile test down

# ── Deployment ──────────────────────────────────────────────────────────────

deploy-staging: ## Deploy to staging server
	$(COMPOSE) build
	$(COMPOSE) push
	@echo "Push complete. Trigger deploy via GitLab CI or run manually on server."

clean: ## Remove build artifacts and containers
	$(COMPOSE) down -v --rmi local
	rm -rf cpp/build/ .tox/ .mypy_cache/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
