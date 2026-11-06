-- Grão: 1 linha por item financeiro (receita ou custo), com valor em BRL.
with itens as (
    select
        item_id, processo, tipo, categoria, moeda, competencia, valor_original, taxa_cambio,
        valor_brl, valor_brl_assinado
    from {{ ref('int_financeiro_brl') }}
),

embarques as (
    select processo, cliente_sk, cliente_id
    from {{ ref('fct_embarque') }}
),

final as (
    select
        itens.item_id,
        itens.processo,
        embarques.cliente_sk,
        embarques.cliente_id,
        itens.tipo,
        itens.categoria,
        itens.moeda,
        itens.competencia as data_competencia,
        itens.valor_original::numeric(16, 2) as valor_original,
        itens.taxa_cambio::numeric(12, 6) as taxa_cambio,
        itens.valor_brl::numeric(16, 2) as valor_brl,
        itens.valor_brl_assinado::numeric(16, 2) as valor_brl_assinado
    from itens
    left join embarques on embarques.processo = itens.processo
)

select
    item_id, processo, cliente_sk, cliente_id, tipo, categoria, moeda, data_competencia,
    valor_original, taxa_cambio, valor_brl, valor_brl_assinado
from final
