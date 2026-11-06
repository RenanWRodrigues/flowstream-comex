---
name: dbt-model
description: Use ao criar ou alterar modelos dbt do FlowStream-Comex (staging, intermediate, marts, snapshots), incluindo dimensões, fatos e KPIs logísticos como on-time, margem, TEUs e demurrage.
---

# Modelo dbt

## Camadas
- staging (schema prata): 1 modelo por tabela de origem; só renomear, tipar,
  padronizar (UN/LOCODE, ISO 4217, maiúsculas) e deduplicar. Prefixo stg_.
- intermediate (prata): joins e regras reutilizáveis. Prefixo int_.
- marts (schema ouro): dim_, fct_ e kpi_. Nunca leem bronze diretamente.

## Passos
1. Escreva o grão em uma frase no topo do .sql (comentário).
2. Escreva primeiro o .yml: descrição, colunas, testes unique e not_null na chave,
   relationships para dimensões, accepted_values em status, e contrato
   (contract: enforced: true) nos modelos de marts.
3. Regras de negócio viram testes singulares em dbt/tests/ (ex.: ata >= atd).
4. SQL com CTEs nomeadas: import -> logic -> final. Sem SELECT *. Materialização:
   staging = view, intermediate = ephemeral, marts = table (ou incremental se > 1M linhas).
5. dbt build --select +<modelo>+ até ficar verde, sem warnings.
6. Se criou fato ou dimensão, atualize docs/modelo_dados.md e o exposures.yml.
