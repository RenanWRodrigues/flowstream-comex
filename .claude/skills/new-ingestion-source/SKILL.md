---
name: new-ingestion-source
description: Use ao adicionar uma nova fonte de dados (API pública, CSV ou arquivo) à camada bronze do FlowStream-Comex. Cria adaptador HTTP, modelo Pydantic, carga idempotente no Postgres, testes com respx, comando na CLI e fonte no dbt.
---

# Nova fonte de ingestão

## Passos (um de cada vez, mostrando o resultado)
1. Leia a documentação pública da fonte e apresente: endpoint, parâmetros, paginação,
   limites e campos usados. Espere confirmação.
2. Salve 2 ou 3 respostas reais em tests/fixtures/<fonte>/ (sem dados pessoais).
3. Escreva tests/unit/ingestion/test_<fonte>.py com respx: sucesso, resposta vazia,
   HTTP 500 com retry, timeout, campo faltando, paginação (se houver). Rode e veja falhar.
4. Implemente em src/flowstream/ingestion/<fonte>.py:
   - domain: modelo Pydantic do registro (Decimal para valores, date para datas)
   - adapter: fetch(start, end) com httpx, timeout 30 s, 3 tentativas com backoff
   - service: load(records) com upsert em bronze.<fonte> (chave natural + loaded_at)
     e registro em ops.pipeline_runs (fonte, início, fim, linhas, status)
5. Comando na CLI: flowstream ingest <fonte> --start --end; alvo make ingest-<fonte>.
6. Declare a fonte em dbt/models/staging/_sources.yml com freshness e testes.
7. Documente em docs/fontes.md: URL, frequência, campos, limitações.
8. Rode make ci.

## Regras
- Carga idempotente: rodar duas vezes o mesmo período não duplica linhas.
- Nunca chame a API real nos testes unitários.
- Teste de integração opcional, marcado com @pytest.mark.integration.
