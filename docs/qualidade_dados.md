# Qualidade de dados

Os testes do dbt dizem se os dados estão certos **agora**; `flowstream quality run` (ou
`make quality`) guarda o resultado de cada execução no banco, para a saúde dos dados virar
histórico, página no Power BI e gatilho de alerta.

## O que uma execução faz

1. **`dbt build`** — seeds, snapshot, modelos e todos os testes de dados (~300). O dbt roda no
   mesmo processo, pela API oficial (`dbtRunner`); a conexão vem do `DATABASE_URL`.
2. **`dbt source freshness`** — se PTAX e Comex Stat estão atualizados.
3. **Monitor de volume** — para cada tabela do bronze, compara as linhas carregadas hoje com a
   média dos dias com carga nos 14 dias anteriores. Desvio maior que 50% (para cima ou para
   baixo) é uma anomalia.
4. **Grava** cada resultado em `ops.dq_results` e cada anomalia em `ops.dq_anomalias`, ligados à
   execução em `ops.pipeline_runs` (pipeline `quality_run`).
5. **Reconstrói `ouro.kpi_saude_dados`**, para o KPI já incluir esta execução.

A execução **reprova** (código de saída 1 e `ERRO` em `ops.pipeline_runs`) se houver teste
falhando, modelo com erro, o dbt falhando antes de rodar, ou fonte com freshness vencida.
Avisos (testes `warn`, fonte em atraso leve) e anomalias de volume **não** reprovam: aparecem
no KPI e no alerta para alguém olhar.

## O que é testado

| Camada | Testes |
| --- | --- |
| Fontes (`bronze`) | chaves únicas; valores aceitos; freshness da PTAX (aviso 4 dias, erro 7) e do Comex Stat (aviso 35 dias, erro 65) |
| Seeds | chaves, relacionamentos, valores aceitos; feriados conferidos contra os dias sem PTAX |
| Staging (`prata`) | chave única e não nula; relacionamentos entre entidades; valores aceitos de status, modal, moeda… |
| Intermediate | PTAX diária sem buracos e repetindo a última cotação útil; conversão para BRL que preserva quantidade e soma; linha do tempo coerente |
| Ouro | contratos (nome e tipo de cada coluna); unicidade no grão; relacionamentos com todas as dimensões; reconciliação dos KPIs com os fatos; regras de negócio (margem, demurrage, cotação ganha, limites físicos, SCD2) |
| Python | regras de domínio (identificadores, timeline, dinheiro) com pytest, antes de qualquer carga |

Lista completa: `make dbt-docs` e abrir `dbt/target/index.html`.

## Onde ver

| Onde | O quê |
| --- | --- |
| `ouro.kpi_saude_dados` | 1 linha por dia: testes ok/aviso/falha, erros, fontes atrasadas, anomalias, `pct_testes_ok`, `saudavel` (página "Saúde dos dados" do Power BI) |
| `ops.dq_results` | Cada teste, modelo e fonte de cada execução, com status, linhas com falha, duração e mensagem (mascarada: sem CNPJ, CPF ou e-mail) |
| `ops.dq_anomalias` | Tabela, linhas no dia, média de 14 dias, desvio e direção |
| `ops.pipeline_runs` | Uma linha por execução (`quality_run`), com o status geral |

```sql
-- O que falhou na última execução?
select tipo, nome, status, linhas_com_falha, mensagem
from ops.dq_results
where run_id = (select max(run_id) from ops.dq_results)
  and status not in ('pass', 'success', 'skipped')
order by tipo, nome;
```

## O que fazer quando falha

| Sintoma | Primeiro passo |
| --- | --- |
| Teste `fail` | Rode o SQL do teste para ver as linhas: `make dbt-show SQL="select * from {{ ref('<modelo>') }} ..."`, ou abra `dbt/target/compiled/flowstream/tests/<teste>.sql`. Corrija a origem (carga ou regra), nunca o teste para "passar" |
| Modelo com `error` | A mensagem traz o erro do banco ou de compilação; detalhes em `dbt/logs/dbt.log` |
| `dbt ... não gerou run_results.json` | O dbt falhou antes de executar (YAML inválido, conexão, pacote faltando): veja `dbt/logs/dbt.log`; `make dbt-deps` se faltar o `dbt_utils` |
| Fonte atrasada | Rode a ingestão (`make ingest-ptax` / `make ingest-comexstat`) e confira `ops.pipeline_runs` da fonte. PTAX não tem cotação em fim de semana e feriado |
| Anomalia `ACIMA` | Carga duplicada ou reprocessamento grande (ex.: `--full-refresh`)? Compare com `ops.pipeline_runs` do dia |
| Anomalia `ABAIXO` | Fonte devolveu menos dados (API parcial, mês ainda não publicado)? A ingestão do Comex Stat recusa meses vazios, mas não meses incompletos |

## Limitações

- O volume é medido pelo `loaded_at` atual: tabelas recarregadas por inteiro (dados
  sintéticos, Comex Stat) "movem" todas as linhas para o dia da recarga, então o histórico de 14
  dias só faz sentido depois de duas semanas de cargas diárias.
- `dbt build` completo leva cerca de 1 a 2 minutos; o pipeline diário (P14) chama esta mesma
  função.
