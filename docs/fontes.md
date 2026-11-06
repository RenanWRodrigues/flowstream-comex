# Fontes de dados

| Fonte | Tabela | Comando | Frequência | Tipo |
| --- | --- | --- | --- | --- |
| Gerador sintético | `bronze.vendedores`, `clientes`, `cotacoes`, `embarques`, `equipamentos`, `itens_financeiros`, `tracking_eventos` | `make synthetic` | Sob demanda | Fictícia ([detalhes](dados_sinteticos.md)) |
| PTAX — Banco Central | `bronze.ptax` | `make ingest-ptax` | Diária (dias úteis) | Pública, real |
| Comex Stat — MDIC | `bronze.comexstat` | `make ingest-comexstat` | Mensal | Pública, real |

Toda execução fica registrada em `ops.pipeline_runs` (início, fim, status, linhas e erro
resumido, sem dados pessoais). As duas fontes reais estão declaradas em
`dbt/models/staging/_sources.yml`, com testes e freshness (`dbt source freshness`).

## PTAX — API Olinda do Banco Central

- **Endpoint:** `GET https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)`
  com `@moeda='USD'`, `@dataInicial='MM-DD-AAAA'`, `@dataFinalCotacao='MM-DD-AAAA'`,
  `$filter=tipoBoletim eq 'Fechamento'` e `$format=json`. Sem autenticação.
- **O que guardamos:** só o boletim de **Fechamento** (a PTAX oficial do dia), para USD e
  EUR: compra, venda, paridade e a hora do boletim.
- **Grão e chave:** uma linha por moeda e dia útil — (`moeda`, `data_cotacao`).
- **Carga:** incremental a partir do dia seguinte ao último carregado de cada moeda (ou de
  `--start`, padrão 2024-01-01, com a tabela vazia), até hoje; `--full-refresh` recarrega
  tudo. Upsert pela chave: rodar de novo não duplica.
- **Volume:** ~250 dias úteis por moeda e ano; 2024-01 a 2026-10 = 713 dias por moeda,
  carregados em ~9 s.

**Limitações e armadilhas (vistas na API real):**

- **Não há PTAX de CNY** (nem de outras moedas fora da lista do endpoint `Moedas`: USD,
  EUR, GBP, JPY, CHF, CAD, AUD, DKK, NOK, SEK). Pedir uma moeda sem PTAX **não dá erro**:
  a API devolve lista vazia. Por isso o código só aceita USD e EUR. O domínio (`Money`)
  aceita CNY, mas os dados do projeto não usam.
- A sintaxe OData precisa ir **literal** na URL (`@`, `$` e aspas): codificados como
  `%40`, `%24`, `%27`, a API responde HTTP 400.
- Datas no formato americano `MM-DD-AAAA`.
- A hora do boletim vem sem fuso (`2025-01-02 13:09:42.489`); é horário de Brasília.
- Cotações vêm como número JSON; o parse lê direto em `Decimal`, sem passar por float.
- Fins de semana e feriados não têm cotação; a camada prata (P05) preenche com a última
  cotação útil.
- Pedidos são divididos por ano-calendário, com 1 s de pausa entre eles. Erros 5xx e de
  rede têm 3 tentativas com backoff exponencial; 4xx falha na hora.

## Comex Stat — MDIC

- **Endpoint:** `POST https://api-comexstat.mdic.gov.br/general?language=pt`. Sem
  autenticação. Documentação: <https://api-comexstat.mdic.gov.br/docs>.
- **Corpo do pedido:** `flow` (`export` ou `import`), `monthDetail: true`, `period`
  (`AAAA-MM` a `AAAA-MM`), filtros `state = 44` (Santa Catarina — atenção: **44** no Comex
  Stat, não o 42 do IBGE) e `via = 01, 04` (marítima e aérea), detalhes `country`,
  `heading` (posição SH4) e `via`.
- **Métricas:** `metricFOB` (US$) e `metricKG` nos dois fluxos; `metricFreight` e
  `metricInsurance` só na importação (a API recusa na exportação).
- **Grão e chave:** fluxo × ano × mês × país × posição SH4 × via. O capítulo (SH2) são os
  2 primeiros dígitos da posição. O país vem pelo **nome** (em português).
- **Janela:** os 24 últimos meses publicados (`GET /general/dates/updated`; em nov/2026,
  out/2024 a set/2026).
- **Carga:** cada pedido **substitui** os meses pedidos (apaga e insere numa transação),
  para refletir as revisões do MDIC, inclusive linhas que somem. O incremental refaz os 3
  últimos meses carregados e acrescenta os novos; `--full-refresh` refaz a janela inteira.
- **Volume:** ~6 mil linhas por mês na exportação e ~8 mil na importação; ~290 mil linhas
  na janela de 24 meses.

**Limitações e armadilhas (vistas na API real):**

- **Período que atravessa a virada do ano devolve lista vazia com HTTP 200.** Por isso os
  pedidos são divididos por ano-calendário (24 meses = 6 pedidos).
- **Resposta vazia ou sem algum mês é tratada como erro**, nunca como carga vazia: SC tem
  comércio em todo mês, então ausência de dados é falha da API, não informação.
- **Limite de taxa agressivo:** HTTP 429 ("tente novamente em 10 segundos") aparece mesmo
  com poucas chamadas, e na prática a espera chega a 1–2 minutos. O cliente pausa 30 s
  entre pedidos e, no 429, espera 30 s e tenta de novo (até 10 vezes). A carga inicial
  leva alguns minutos.
- Um ano de importação vem num único JSON de ~34 MB (~100 mil linhas, ~15 s).
- Métricas vêm como **texto** (`"53908342"`); o parse converte para `Decimal`.
- A spec OpenAPI não documenta o formato da resposta; os nomes dos campos (`year`,
  `monthNumber`, `country`, `headingCode`, `heading`, `via`, `metric*`) vêm das respostas
  reais em `tests/fixtures/comexstat/`.
- Erros 5xx e de rede: 3 tentativas com backoff; 4xx falha na hora, mostrando a mensagem
  da API.
