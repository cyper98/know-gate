.PHONY: help up down logs ps restart build pull migrate seed test lint format clean cli-install secrets

# Default: show help
help:
	@echo "KnowGate MVP - dev commands"
	@echo ""
	@echo "  make up           Start all services (docker compose up -d)"
	@echo "  make down         Stop all services"
	@echo "  make logs         Tail logs (all services)"
	@echo "  make ps           List running services"
	@echo "  make restart      Restart all services"
	@echo "  make build        Build images"
	@echo "  make pull         Pull latest base images"
	@echo "  make migrate      Run DB migrations"
	@echo "  make seed         Seed initial data (admin user + roles)"
	@echo "  make test         Run backend tests"
	@echo "  make lint         Run linters (ruff + eslint)"
	@echo "  make format       Run formatters (ruff format + prettier)"
	@echo "  make clean        Remove all containers + volumes (DESTRUCTIVE)"
	@echo "  make secrets      Generate JWT key pair + encryption key"
	@echo "  make cli-install  Install CLI in editable mode"
	@echo ""

# Load .env if exists (so make targets see env vars)
ifneq (,$(wildcard .env))
    include .env
    export
endif

COMPOSE := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml

up:
	$(COMPOSE) up -d
	@echo ""
	@echo "Services up. Health check:"
	@curl -sf http://localhost:8000/health || echo "API not ready yet (try make logs)"
	@echo ""
	@echo "Web UI:    http://localhost:3000"
	@echo "API:       http://localhost:8000/docs"
	@echo "MinIO:     http://localhost:9001 (knowgate / knowgate_dev_pwd)"
	@echo "MailHog:   http://localhost:8025"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) restart

build:
	$(COMPOSE) build

pull:
	$(COMPOSE) pull

migrate:
	$(COMPOSE) exec api alembic upgrade head

seed:
	$(COMPOSE) exec api python -m scripts.seed

install:
	cd backend && python3 -m venv .venv
	cd backend && .venv/bin/pip install --upgrade pip
	cd backend && .venv/bin/pip install -e ".[dev]"
	@echo "✓ Backend installed in backend/.venv"
	@echo "  Next: cd frontend && npm install"

test: install
	cd backend && .venv/bin/pytest

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

format:
	cd backend && ruff format .
	cd frontend && npm run format

clean:
	$(COMPOSE) down -v --remove-orphans
	docker system prune -f

secrets:
	@mkdir -p secrets
	@openssl genrsa -out secrets/jwt_private.pem 2048 2>/dev/null
	@openssl rsa -in secrets/jwt_private.pem -pubout -out secrets/jwt_public.pem 2>/dev/null
	@echo "JWT key pair generated in secrets/"
	@echo "Add to .env: KG_ENCRYPTION_KEY=$$(python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"

cli-install:
	cd cli && pip install -e .
