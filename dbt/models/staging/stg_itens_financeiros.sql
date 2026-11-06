-- Grão: 1 linha por item financeiro (receita ou custo), na moeda original.
with origem as (
    select item_id, processo, tipo, categoria, valor, moeda, competencia
    from {{ source('bronze', 'itens_financeiros') }}
),

final as (
    select
        upper(trim(item_id)) as item_id,
        upper(trim(processo)) as processo,
        upper(trim(tipo)) as tipo,
        upper(trim(categoria)) as categoria,
        valor::numeric(14, 2) as valor,
        upper(trim(moeda)) as moeda,
        competencia
    from origem
)

select item_id, processo, tipo, categoria, valor, moeda, competencia
from final
