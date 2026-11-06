# dbt/

Projeto dbt que transforma o schema `bronze` (dados como chegaram) nas camadas
`prata` (padronizada) e `ouro` (star schema e KPIs). Modelo completo em
[docs/modelo_dados.md](../docs/modelo_dados.md).

- **Conexão:** `profiles.yml` lê `APP_DB_USER`, `APP_DB_PASSWORD`, `POSTGRES_PORT` e
  `POSTGRES_DB` do ambiente; o Makefile os carrega do `.env`. Nenhuma senha no repositório.
- **Schemas:** a macro `generate_schema_name` usa o schema configurado sem prefixo
  (`prata`, `ouro`), em vez do `<profile>_<custom>` padrão do dbt.
- **Pacotes:** `dbt_utils` (versão travada em `package-lock.yml`); `make dbt` instala
  sozinho num clone novo.

| Comando | O que faz |
| --- | --- |
| `make dbt` | `dbt build`: seeds, modelos e todos os testes (precisa do Postgres) |
| `make dbt-seed` | Só os seeds |
| `make dbt-freshness` | Freshness das fontes públicas |
| `make dbt-show SQL="select ..."` | Consulta qualquer modelo, inclusive os ephemeral (ex.: `select * from {{ ref('int_ptax_diaria') }}`) |
| `make dbt-docs` | Gera o catálogo navegável (`dbt/target/index.html`) |
| `make dbt-deps` | Reinstala os pacotes |

| Pasta | Conteúdo |
| --- | --- |
| `models/staging/` | `stg_*` — um modelo por tabela do bronze (schema prata, views) |
| `models/intermediate/` | `int_*` — joins e regras reutilizáveis (prata, ephemeral) |
| `models/marts/` | `dim_*`, `fct_*`, `kpi_*` (schema ouro, tabelas com contrato) e `exposures.yml` |
| `seeds/` | Dados de referência: feriados, portos, aeroportos, países, moedas, segmentos, armadores e cias. aéreas (fictícios) e rotas; documentados e testados em `seeds.yml` |
| `snapshots/` | `snap_clientes`: histórico SCD tipo 2 dos clientes |
| `tests/` | Testes singulares de regras de negócio e das macros |
| `macros/` | `to_brl`, `dias_uteis_entre`, `generate_schema_name` |

## Camada prata

**Staging** (views; só renomeia, tipa e padroniza códigos em maiúsculas):

| Modelo | Grão | Origem |
| --- | --- | --- |
| `stg_vendedores` | vendedor | `bronze.vendedores` |
| `stg_clientes` | cliente | `bronze.clientes` |
| `stg_cotacoes` | cotação | `bronze.cotacoes` |
| `stg_embarques` | processo | `bronze.embarques` |
| `stg_equipamentos` | contêiner ou isotanque de um processo | `bronze.equipamentos` |
| `stg_itens_financeiros` | item financeiro, na moeda original | `bronze.itens_financeiros` |
| `stg_tracking` | evento de rastreamento | `bronze.tracking_eventos` |
| `stg_ptax` | moeda × dia útil | `bronze.ptax` |
| `stg_comexstat` | fluxo × mês × país × posição SH4 × via; com `sh2_codigo` e `mes_referencia` | `bronze.comexstat` |

**Intermediate** (ephemeral; viram CTEs nos modelos que os usam):

| Modelo | Grão | Regra |
| --- | --- | --- |
| `int_ptax_diaria` | moeda (BRL, USD, EUR) × dia corrido | Fins de semana e feriados repetem a última PTAX útil; BRL tem taxa 1 |
| `int_embarque_timeline` | processo | Transit previsto e real, atrasos de saída e chegada, `chegou_no_prazo` (ATA ≤ ETA + 1 dia), dias úteis entre booking e ETD |
| `int_financeiro_brl` | item financeiro | Valor em BRL pela PTAX de venda da data de competência; `valor_brl_assinado` (receita +, custo −) |

**Macros:**

- `to_brl(valor, moeda, data)` — converte pela PTAX de venda do dia (via `int_ptax_diaria`).
  Moeda sem PTAX (ex.: CNY) devolve NULL de propósito, para o teste `not_null` acusar.
- `dias_uteis_entre(inicio, fim)` — dias de segunda a sexta depois de `inicio` até `fim`.
  Desconta os feriados do seed `feriados`.

**Testes singulares** (`tests/`): sem buracos na PTAX diária; dia sem PTAX repete a última
útil; a conversão preserva a quantidade e a soma em moeda original; BRL não muda e a moeda
estrangeira é `valor × taxa`; linha do tempo coerente; casos conhecidos das duas macros.

Convenções na skill `.claude/skills/dbt-model`.

## Camada ouro

Star schema (7 dimensões, 4 fatos) e 6 KPIs, todos com contrato imposto. Grãos, chaves,
regras e o diagrama estão em [docs/modelo_dados.md](../docs/modelo_dados.md).
