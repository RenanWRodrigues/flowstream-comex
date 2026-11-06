# Changelog

Todas as mudanças relevantes do projeto são registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto
usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
- Pacote `flowstream` instalável (hatchling), Python 3.11, com a CLI `flowstream` e os
  grupos `ingest`, `synthetic`, `ai` e `export` (em construção) e o comando `version`.
- `flowstream.config.Settings`: configuração por variáveis de ambiente, com segredos em
  `SecretStr` e mensagem clara quando falta `DATABASE_URL`.
- `flowstream.logging`: JSON em arquivo, texto no terminal e mascaramento de CNPJ, CPF e
  e-mail, inclusive em tracebacks.
- Makefile (`install`, `up`, `down`, `test`, `test-int`, `lint`, `format`, `dbt`, `ci`,
  `pre-commit`), pre-commit com ruff, mypy, pytest e verificações de arquivos.
- Estrutura de pastas completa, com README em cada pasta de primeiro nível.
- Documentação inicial: arquitetura, glossário, diário de bordo e ADR 0001 (stack gratuita).
- Configuração do Claude Code: `CLAUDE.md`, hooks, skills e subagentes do projeto.
- `.env.example` com todas as variáveis e valores fictícios; variáveis vazias assumem o
  valor padrão.
- `.gitattributes` com quebras de linha LF; `PYTHONUTF8=1` exportado pelo Makefile para
  acentos corretos no Git Bash do Windows.

- Infraestrutura Docker (P01): PostgreSQL 16 e n8n com `mem_limit 512m`, portas só em
  127.0.0.1, healthcheck e senhas só no `.env`; porta do Postgres configurável por
  `POSTGRES_PORT` (5433 no modelo).
- `infra/init/00_databases.sh`: usuário da aplicação com permissões mínimas e banco
  separado para o n8n.
- Migrações SQL versionadas em `infra/migrations/` (001: schemas bronze, prata, ouro e
  ops; 002: `ops.pipeline_runs`), aplicadas por `flowstream db migrate` e registradas em
  `ops.schema_migrations` com checksum.
- `flowstream.db`: engine SQLAlchemy, transação e runner de migrações.
- Alvos `up-all`, `psql`, `db-migrate` e `db-reset` no Makefile; `docs/runbook.md`;
  ADR 0002 (migrações em SQL puro em vez de Alembic).

- Núcleo de domínio (P02) em `flowstream.domain`, Python puro:
  - `identifiers`: tipos Pydantic que validam e normalizam contêiner (ISO 6346), AWB
    (módulo 7), NCM, CNPJ (numérico e alfanumérico, em vigor desde 07/2026), UN/LOCODE e
    IATA; geradores reprodutíveis de contêineres e AWBs válidos.
  - `money`: `Money` em Decimal (recusa float), soma só na mesma moeda, conversão com
    arredondamento bancário em 2 casas.
  - `shipment`: enums de modal, direção e status; `validate_timeline` com 7 regras.
  - `dates`: fuso America/Sao_Paulo e recusa de datas sem fuso.
- Seeds do dbt (portos, aeroportos, países, moedas, segmentos, armadores e cias. aéreas
  fictícios, rotas com transit time), documentados e testados em `seeds.yml` e conferidos
  com o domínio por `tests/unit/test_seeds.py`.
- Projeto dbt mínimo (`dbt_project.yml`, `profiles.yml` lendo o ambiente e macro
  `generate_schema_name`); alvo `make dbt-seed`. `make dbt` deixa de ser pulado.

- Gerador de dados sintéticos (P03) em `flowstream.synthetic`: 24 meses de operação
  fictícia (300 clientes, 6.000 cotações, 1.800 embarques, financeiro e tracking) com
  sazonalidade, Ano-Novo Chinês, pontualidade por armador, margem de 8% a 25% e demurrage
  absorvida; configuração em `synthetic/config.yaml`; reprodutível pela semente.
- `flowstream synthetic generate` (CSVs em `data/synthetic`) e `flowstream synthetic load`
  (`TRUNCATE` + `COPY` numa transação, idempotente); alvo `make synthetic`.
- Migração 003 com as tabelas sintéticas do bronze; `flowstream.pipeline_runs` registra
  início, fim, linhas e erro (mascarado) de cada carga em `ops.pipeline_runs`.
- `cnpj_check_digits` público no domínio; dependência `pyyaml` (e `types-PyYAML` no dev).
- `docs/dados_sinteticos.md`. Correções da auditoria de qualidade de dados: atraso
  proporcional ao modal e à rota, frete do 20' menor que o do 40'HC, demurrage só na
  importação, Pareto de clientes realista, ocupação prática dos contêineres e Ano-Novo
  Chinês modelado como carga adiada.

- Ingestão de APIs públicas (P04):
  - `flowstream ingest ptax`: PTAX de fechamento (USD, EUR) da API Olinda do BCB,
    incremental por moeda, upsert em `bronze.ptax` (migração 004).
  - `flowstream ingest comexstat`: exportação e importação de SC (Comex Stat/MDIC) por mês,
    país, posição SH4 e via, 24 meses, com frete e seguro na importação; cada carga
    substitui os meses pedidos e o incremental refaz os 3 últimos (migração 005).
  - Retry com backoff, espera em HTTP 429, divisão por ano-calendário e detecção de
    respostas vazias silenciosas; tudo registrado em `ops.pipeline_runs`.
  - Fontes declaradas no dbt (`_sources.yml`) com testes e freshness; `docs/fontes.md`;
    fixtures reais em `tests/fixtures/`; alvos `make ingest-ptax` e `make ingest-comexstat`.

- Camada prata no dbt (P05): 9 modelos de staging (views) para todas as tabelas do
  bronze; `int_ptax_diaria` (PTAX em todo dia corrido), `int_embarque_timeline` (prazos,
  atrasos e on-time) e `int_financeiro_brl` (conversão pela PTAX da competência); macros
  `to_brl` e `dias_uteis_entre`; testes singulares das regras e das macros; pacote
  `dbt_utils`; alvos `make dbt-show` e `make dbt-deps`.
- Camada ouro no dbt (P06): snapshot SCD2 `snap_clientes`; 7 dimensões (`dim_data` com
  feriados, `dim_cliente` SCD2, `dim_vendedor`, `dim_rota`, `dim_porto` com aeroportos,
  `dim_modal`, `dim_parceiro`); 4 fatos (`fct_embarque`, `fct_financeiro`, `fct_cotacao`,
  `fct_tracking_evento`); 6 KPIs (on-time por armador, margem por processo, risco de
  demurrage, win rate, tempo de resposta, mercado de SC); contratos impostos com precisão
  numérica; `exposures.yml`; `docs/modelo_dados.md`; alvo `make dbt-docs`.
- Seed `feriados` (2023–2027, nacionais e bancários), conferido contra os dias sem PTAX;
  `dias_uteis_entre` passa a descontar feriados.
- Correções da auditoria da camada ouro: evento `DEVOLUCAO_VAZIO` no tracking sintético
  (demurrage cobrada na devolução atrasada) e risco de demurrage baseado nele; cotações,
  respostas e bookings em dias úteis e horário comercial; tempo de resposta sem pico no
  teto e sem resposta depois do corte; `mes_fechado` nos KPIs mensais; macro
  `data_de_corte`; testes de reconciliação dos KPIs e de grão dos fatos.
- Qualidade e observabilidade (P07): `flowstream quality run` / `make quality` roda
  `dbt build` e `dbt source freshness` no mesmo processo (`dbtRunner`, conexão derivada
  do `DATABASE_URL`), lê `run_results.json` e `sources.json` e grava em
  `ops.dq_results`; monitor de volume do bronze (±50% da média de 14 dias) em
  `ops.dq_anomalias` (migração 006); modelo `kpi_saude_dados`; fonte `ops` no dbt;
  `docs/qualidade_dados.md`.
- API FastAPI (P08): `GET /health` (pública; banco e Ollama), `GET /v1/tracking/{contêiner}`
  (ISO 6346 validada), `GET /v1/embarques/risco?dias=3`, `POST /v1/documentos` (PDF da
  inbox, anti path traversal, SHA-256 contra duplicados, 202) e `GET /v1/documentos/{id}`;
  chave `X-API-Key`; erros RFC 9457 (`problem+json`) sem stack trace; interface
  `DocumentProcessor` (P10 troca a implementação); migração 007 (`ops.documentos`);
  `make api`; `docs/api.md`. Dependências `fastapi` e `uvicorn`.
- Entrada automática de documentos (P09): watcher da `data/inbox`
  (`flowstream.ingestion.inbox_watcher`, `make watch`) que ignora temporários e não-PDF,
  espera o arquivo parar de crescer, calcula o SHA-256, move duplicados para
  `data/processed/duplicados` e avisa o webhook do n8n (3 tentativas com backoff; falha
  definitiva vira `ERRO` em `ops.pipeline_runs`). Estabilidade por tamanho e mtime, espera
  crescente quando o banco cai, erro inesperado num arquivo não derruba o processo, webhook
  sem proxy nem redirecionamento. Usa ~46 MB de RAM: `psycopg` direto e `urllib`, sem
  SQLAlchemy nem httpx. Também `flowstream inbox watch`.
- Fluxo n8n `documento_recebido` (`n8n/flows/`): webhook autenticado por `X-Webhook-Token`
  -> abre a execução em `ops.pipeline_runs` e só então responde 202 -> `POST /v1/documentos`; Error Trigger com alerta no
  Telegram (nó desativado até o P13). Consultas em `n8n/sql/` com teste de integração.
- `flowstream n8n clean-export`: limpa o JSON exportado (sem ids de credenciais nem
  `pinData`); teste que barra segredo e SQL fora de `n8n/sql/` nos fluxos versionados.
- Variáveis `N8N_WEBHOOK_TOKEN` e `PROCESSED_DIR`; `docs/n8n.md`; PDF fictício em
  `tests/fixtures/documentos/`. Dependência `watchdog`.
- Agente de extração de documentos (P10) em `flowstream.ai`: BL, AWB, commercial invoice
  e packing list em JSON validado, com evidence por campo, score ponderado (C=3, O=1,
  op=0,5) e decisão APROVADO (score ≥ 0,90 e nenhuma divergência crítica) ou REVISAO.
  Texto por página com pdfplumber e OCR Tesseract (por+eng) em página escaneada;
  classificação por regras (LLM só no empate); Ollama com temperature 0, JSON,
  `num_ctx` 4096 e uma chamada por vez; 1 nova tentativa só para erro de estrutura.
  Validadores de formato, coerência, grounding (RapidFuzz; sempre crítico), cruzamento
  BL/AWB × packing list × invoice e texto suspeito (prompt injection).
- Migração 008 (`ops.extracoes`, com `check` que impede APROVADO abaixo de 0,90); a API
  passa a extrair de verdade (`QueuedDocumentProcessor`: fila com um worker);
  `flowstream ai extract`; variável `TESSERACT_CMD`; prompts versionados
  (`ai/prompts/<tipo>_v1.md`); PDFs fictícios gerados com reportlab, inclusive escaneado
  e com tentativa de injeção; `docs/agente_ia.md` e `docs/riscos_ia.md`. Dependências
  `pdfplumber`, `pytesseract`, `rapidfuzz` e `reportlab` (dev).
- Avaliação do agente com gabarito (P11): conjunto de 40 documentos fictícios em
  `tests/eval/` (10 por tipo, 3 layouts, 5 escaneados, 5 com erro proposital e 3 com
  tentativa de injeção, uma delas oculta), gerado de forma reprodutível por
  `tests/eval/generate.py`, cada um com gabarito JSON (texto, valores e evidências). Um
  teste roda o pipeline real com um extrator perfeito nos 40 PDFs: o gabarito precisa dar
  100% e a decisão esperada.
- `flowstream ai evaluate --prompt-version --model` (`make evaluate`), em
  `ai/evaluation.py`: acurácia por campo (exata e normalizada), acurácia dos críticos,
  acurácia dos campos preenchidos, taxa de alucinação (token inteiro, também com tipo
  errado), recall dos erros plantados pela regra esperada, injeções e armadilhas aprovadas,
  aprovados com crítico errado, aprovação automática e tempo médio e p95. Sai com código 1
  se alguma armadilha, ou documento com crítico errado, for aprovada; execução com documento
  em ERRO não é gravada. `--timeout` (padrão 600 s) para a CPU de 8 GB. Resultado em
  `ops.avaliacoes_ia` (migração 009, com o SHA-256 do conjunto) e no histórico de
  `docs/ia_avaliacao.md`.
- `ExtractionPipeline(prompt_version=...)` e `check_prompt_version`: versão de prompt
  escolhida na execução, validada (`v<n>`, sem caminho) e com arquivo para os 4 tipos.

### Corrigido
- Os testes de integração da carga sintética sobrescreviam o `bronze` real com um
  conjunto de 2 meses; agora usam um schema temporário isolado (`schema` no loader).

### Alterado
- `documents.service.digest_file` passa a ser público (o watcher e a API calculam o
  SHA-256 do mesmo jeito).
- O filtro de logs também mascara CNPJ alfanumérico.
- `known-first-party = ["flowstream"]` no ruff: no TDD o teste nasce antes do módulo, e a
  ordem dos imports não depende mais de o arquivo existir.
- Endereços locais usam `127.0.0.1` em vez de `localhost` (padrões do `Settings` e
  `.env.example`), e o engine do banco tem `connect_timeout` de 10 s: no Windows,
  `localhost` tenta IPv6 primeiro e cada conexão ao Postgres do Docker levava dezenas de
  segundos.
- `make lint` e o pre-commit rodam o ruff sem cache: o cache escondia imports fora de
  ordem quando o teste era escrito antes do módulo.
- Hook `format_python.py` usa o ruff do `.venv` (mesma versão do `make lint`) e ignora
  arquivos fora do projeto.
- Hook `protect_files.py` libera só o `.env.example`; as regras de leitura negada do
  `settings.json` passam a citar `.env`, `.env.local`, `.env.*.local` e `.env.production`.
