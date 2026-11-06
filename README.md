# FlowStream-Comex

Plataforma de dados para um agente de cargas internacional (marítimo FCL/LCL, aéreo,
rodoviário e isotanque). Recebe embarques, cotações, custos, câmbio, estatísticas de
comércio exterior e documentos de embarque; organiza tudo em PostgreSQL nas camadas
bronze, prata e ouro; usa um agente de IA local para extrair e validar documentos;
dispara alertas operacionais pelo n8n; e entrega os indicadores no Power BI.

> **Status:** em construção — fase 2 (dados). Veja o [CHANGELOG](CHANGELOG.md).

## Princípios

- **Gratuito e local:** só software livre e APIs públicas, rodando em 8 GB de RAM.
- **Testes primeiro:** nenhum código de produção sem um teste que falhou antes.
- **IA sob controle:** toda saída do modelo é validada; o que não passa vai para revisão humana.
- **Documentado enquanto é feito:** `docs/`, `CHANGELOG.md` e ADRs a cada etapa.

## Como rodar (Python 3.11)

```bash
# Windows (Git Bash) — no Linux/macOS use: python3.11 -m venv .venv && source .venv/bin/activate
py -3.11 -m venv .venv
source .venv/Scripts/activate
make install          # pacote em modo editável + dependências de dev + pre-commit
cp .env.example .env  # e ajuste os valores
make ci               # lint + testes + dbt
flowstream --help

# Infraestrutura (Docker Desktop aberto)
make up-all           # Postgres + n8n, com 512 MB de memória cada
make db-migrate       # cria os schemas bronze, prata, ouro e ops
make synthetic        # 24 meses de operação fictícia no bronze
make ingest-ptax      # câmbio oficial do Banco Central
make ingest-comexstat # comércio exterior de SC (Comex Stat)
make dbt              # camadas prata e ouro (star schema e KPIs) e todos os testes
make test-int         # testes de integração contra o Postgres
```

Detalhes de operação e solução de problemas em [docs/runbook.md](docs/runbook.md).

**Windows:** para os acentos saírem certos no Git Bash, ative o modo UTF-8 do Python uma
vez com `setx PYTHONUTF8 1` (vale para os próximos terminais). O Makefile já faz isso nos
seus alvos.

## Comandos

| Comando | O que faz |
| --- | --- |
| `make install` | Instala o pacote com os extras de desenvolvimento e os hooks do pre-commit |
| `make test` | Testes unitários (sem rede, banco ou Ollama) |
| `make test-int` | Testes de integração (precisam do Postgres) |
| `make lint` | ruff (lint e formatação) e mypy estrito |
| `make synthetic` | Gera 24 meses de operação fictícia (semente 42) e carrega no bronze |
| `make ingest-ptax` | PTAX (USD, EUR) do Banco Central, incremental |
| `make ingest-comexstat` | Comércio exterior de SC (Comex Stat), 24 meses; leva alguns minutos |
| `make api` | Sobe a API em http://127.0.0.1:8000 (Swagger em `/docs`) |
| `flowstream ai extract arquivo.pdf` | Extrai e valida um documento com o agente de IA (precisa do Ollama; [docs/agente_ia.md](docs/agente_ia.md)) |
| `make evaluate` | Avalia o agente de IA nos 40 documentos com gabarito de `tests/eval` ([docs/ia_avaliacao.md](docs/ia_avaliacao.md)) |
| `make watch` | Observa `data/inbox` e envia cada PDF novo ao n8n ([docs/n8n.md](docs/n8n.md)) |
| `make quality` | Roda o dbt e grava testes, freshness e anomalias de volume no banco |
| `make dbt-freshness` | Confere se PTAX e Comex Stat estão atualizados |
| `make dbt-docs` | Gera o catálogo navegável do dbt |
| `make dbt-show SQL="..."` | Consulta qualquer modelo dbt, inclusive os intermediários |
| `make dbt-seed` | Carrega os dados de referência (portos, rotas, moedas…) no schema prata |
| `make dbt` | `dbt build`: seeds, modelos e testes de dados (precisa do Postgres) |
| `make ci` | lint + test + dbt — rode antes de todo commit, com o Postgres de pé |
| `make pre-commit` | Roda todos os hooks do pre-commit em todos os arquivos |
| `make format` | Formata o código e aplica as correções automáticas do ruff |
| `make up` / `make up-all` | Sobe o Postgres (ou Postgres e n8n) e espera o healthcheck |
| `make down` | Para os containers; os dados ficam nos volumes |
| `make db-migrate` | Aplica as migrações SQL pendentes |
| `make psql` | Abre o psql no banco do projeto |
| `make db-reset` | Apaga e recria o banco (pede confirmação) |

## Documentação

- [Arquitetura](docs/arquitetura.md)
- [Glossário de comércio exterior](docs/glossario.md)
- [Fontes de dados](docs/fontes.md)
- [Modelo de dados (star schema)](docs/modelo_dados.md)
- [Qualidade de dados](docs/qualidade_dados.md)
- [API](docs/api.md)
- [Agente de IA](docs/agente_ia.md) e [avaliação com gabarito](docs/ia_avaliacao.md)
- [Decisões de arquitetura (ADRs)](docs/adr/README.md)
- [Diário de bordo](docs/diario.md)

## Estrutura

| Pasta | Conteúdo |
| --- | --- |
| `src/flowstream/` | Pacote Python: CLI, configuração, logging e módulos de negócio |
| `tests/` | Testes unitários, de integração, fixtures e avaliação da IA |
| `dbt/` | Modelos dbt das camadas prata e ouro |
| `infra/` | Docker Compose, scripts de inicialização e migrações SQL |
| `n8n/` | Fluxos exportados do n8n e as consultas SQL que eles usam |
| `powerbi/` | Medidas DAX, tema e guia de montagem do relatório |
| `data/` | Arquivos de dados locais (fora do Git, exceto a estrutura) |
| `docs/` | Documentação do projeto e ADRs |
