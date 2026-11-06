# FlowStream-Comex — alvos de desenvolvimento.
# Funciona no Git Bash (Windows) e no Linux/macOS, sempre com o python do .venv.
# Mensagens dentro das receitas ficam em ASCII: o make do Windows corrompe acentos nelas.

ifeq ($(OS),Windows_NT)
VENV_BIN := .venv/Scripts
else
VENV_BIN := .venv/bin
endif

PY           := $(VENV_BIN)/python
DBT          := $(VENV_BIN)/dbt
FLOWSTREAM   := $(VENV_BIN)/flowstream
COMPOSE_FILE := infra/docker-compose.yml
COMPOSE      := docker compose -f $(COMPOSE_FILE) --env-file .env
SERVICES     ?= postgres

DBT_ARGS     := --project-dir dbt --profiles-dir dbt

# No Windows, o Python usa cp1252 quando a saída vai para um pipe; força UTF-8.
export PYTHONUTF8 := 1

# O dbt lê a conexão de variáveis de ambiente (dbt/profiles.yml): carrega só estas do .env.
# Limitação: valores com $ ou # no .env não funcionam aqui.
-include .env
export APP_DB_USER APP_DB_PASSWORD POSTGRES_PORT POSTGRES_DB

.DEFAULT_GOAL := help
.PHONY: help check-venv check-env install up up-all down psql db-migrate db-reset dbt-seed synthetic \
	ingest-ptax ingest-comexstat dbt-freshness dbt-deps dbt-show dbt-docs quality api watch evaluate \
	test test-int lint format dbt ci pre-commit

help: ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | \
		awk -F '\t' '{printf "  %-12s %s\n", $$1, $$2}'

check-venv:
	@test -f "$(PY)" || test -f "$(PY).exe" || { \
		echo "Falta o ambiente virtual .venv: crie com Python 3.11 (veja o README)."; \
		exit 1; }

check-env:
	@test -f .env || { echo "Falta o arquivo .env: rode  cp .env.example .env  e ajuste as senhas."; exit 1; }

install: check-venv ## Instala o pacote (editável) com extras de dev e os hooks do pre-commit
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m pre_commit install

# ------------------------------------------------------------------ Docker e banco

up: check-env ## Sobe os containers e espera ficarem saudáveis (padrão: SERVICES="postgres")
	$(COMPOSE) up -d --wait $(SERVICES)

up-all: check-env ## Sobe Postgres e n8n
	$(COMPOSE) up -d --wait postgres n8n

down: check-env ## Derruba todos os containers (os dados ficam nos volumes)
	$(COMPOSE) down

psql: check-env ## Abre o psql no banco do projeto, como usuário da aplicação
	$(COMPOSE) exec postgres sh -c 'psql -U "$$APP_DB_USER" -d "$$POSTGRES_DB"'

db-migrate: check-venv check-env ## Aplica as migrações pendentes de infra/migrations
	$(FLOWSTREAM) db migrate

db-reset: check-venv check-env ## APAGA os dados do Postgres e do n8n, recria e migra (pede confirmação)
	@printf "Isto APAGA todos os dados do Postgres e do n8n (volumes). Digite sim para continuar: "; \
	read -r answer; \
	if [ "$$answer" != "sim" ]; then echo "Cancelado."; exit 1; fi
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait postgres
	$(FLOWSTREAM) db migrate

# ------------------------------------------------------------------ dados

synthetic: check-venv check-env ## Gera os dados sintéticos (semente 42) e carrega no bronze
	$(FLOWSTREAM) synthetic generate --seed 42
	$(FLOWSTREAM) synthetic load

api: check-venv check-env ## Sobe a API em http://127.0.0.1:8000 (Swagger em /docs), com recarga
	$(PY) -m uvicorn flowstream.api.app:app --reload --host 127.0.0.1 --port 8000

watch: check-venv check-env ## Observa data/inbox e avisa o n8n de cada PDF novo (Ctrl+C para parar)
	$(PY) -m flowstream.ingestion.inbox_watcher

evaluate: check-venv check-env ## Avalia o agente de IA com o gabarito de tests/eval (precisa do Ollama)
	$(FLOWSTREAM) ai evaluate

quality: check-venv check-env dbt/dbt_packages ## dbt build + freshness + volume, gravados em ops (flowstream quality run)
	$(FLOWSTREAM) quality run

ingest-ptax: check-venv check-env ## PTAX (USD, EUR) do Banco Central, incremental
	$(FLOWSTREAM) ingest ptax

ingest-comexstat: check-venv check-env ## Comex Stat de SC (24 meses), incremental; leva minutos
	$(FLOWSTREAM) ingest comexstat

# ------------------------------------------------------------------ qualidade

test: check-venv ## Testes unitários (sem rede, banco ou Ollama)
	$(PY) -m pytest -q -m "not integration"

test-int: check-venv ## Testes de integração (precisam do Postgres: make up)
	@$(PY) -m pytest -m integration --no-cov; status=$$?; \
	if [ $$status -eq 5 ]; then echo "Sem testes marcados como integration por enquanto."; else exit $$status; fi

lint: check-venv ## ruff (lint e formatação) e mypy estrito
	$(PY) -m ruff check --no-cache .
	$(PY) -m ruff format --no-cache --check .
	$(PY) -m mypy src

format: check-venv ## Formata o código e aplica correções automáticas do ruff
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

dbt-deps: check-venv ## Instala os pacotes do dbt (dbt_utils) conforme o package-lock.yml
	$(DBT) deps $(DBT_ARGS)

dbt/dbt_packages:
	$(DBT) deps $(DBT_ARGS)

dbt: check-venv check-env dbt/dbt_packages ## dbt build: seeds, modelos e testes de dados (precisa do Postgres)
	$(DBT) build $(DBT_ARGS)

dbt-seed: check-venv check-env dbt/dbt_packages ## Carrega os dados de referência (dbt/seeds) no schema prata
	$(DBT) seed $(DBT_ARGS)

dbt-show: check-venv check-env dbt/dbt_packages ## Roda um SELECT no dbt (inclui modelos ephemeral): make dbt-show SQL="select ..."
	$(DBT) show $(DBT_ARGS) --inline "$(SQL)" --limit 50

dbt-docs: check-venv check-env dbt/dbt_packages ## Gera o catálogo navegável em dbt/target/index.html
	$(DBT) docs generate $(DBT_ARGS)

dbt-freshness: check-venv check-env dbt/dbt_packages ## Confere se as fontes (PTAX, Comex Stat) estão atualizadas
	$(DBT) source freshness $(DBT_ARGS)

ci: lint test dbt ## lint + test + dbt — rode antes de todo commit

pre-commit: check-venv ## Roda todos os hooks do pre-commit em todos os arquivos
	$(PY) -m pre_commit run --all-files
