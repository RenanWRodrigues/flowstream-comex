-- Grão: 1 linha por item financeiro, com o valor em BRL pela PTAX de venda da competência.
with itens as (
    select item_id, processo, tipo, categoria, valor, moeda, competencia
    from {{ ref('stg_itens_financeiros') }}
),

ptax as (
    select moeda, data, cotacao_venda
    from {{ ref('int_ptax_diaria') }}
),

convertido as (
    select
        itens.item_id,
        itens.processo,
        itens.tipo,
        itens.categoria,
        itens.moeda,
        itens.competencia,
        itens.valor as valor_original,
        ptax.cotacao_venda as taxa_cambio,
        {{ to_brl('itens.valor', 'itens.moeda', 'itens.competencia') }} as valor_brl
    from itens
    left join ptax on ptax.moeda = itens.moeda and ptax.data = itens.competencia
),

final as (
    select
        item_id, processo, tipo, categoria, moeda, competencia, valor_original, taxa_cambio,
        valor_brl,
        case when tipo = 'RECEITA' then valor_brl else -valor_brl end as valor_brl_assinado
    from convertido
)

select
    item_id, processo, tipo, categoria, moeda, competencia, valor_original, taxa_cambio,
    valor_brl, valor_brl_assinado
from final
