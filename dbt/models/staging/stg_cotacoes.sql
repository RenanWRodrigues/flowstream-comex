-- Grão: 1 linha por cotação.
with origem as (
    select
        cotacao_id, cliente_id, vendedor_id, modal, direcao, rota_codigo, origem, destino,
        solicitada_em, respondida_em, valor_frete, moeda, quantidade_equipamentos,
        peso_kg, volume_m3, status, motivo_perda
    from {{ source('bronze', 'cotacoes') }}
),

final as (
    select
        upper(trim(cotacao_id)) as cotacao_id,
        upper(trim(cliente_id)) as cliente_id,
        upper(trim(vendedor_id)) as vendedor_id,
        upper(trim(modal)) as modal,
        upper(trim(direcao)) as direcao,
        upper(trim(rota_codigo)) as rota_codigo,
        upper(replace(origem, ' ', '')) as origem,
        upper(replace(destino, ' ', '')) as destino,
        solicitada_em,
        respondida_em,
        valor_frete::numeric(14, 2) as valor_frete,
        upper(trim(moeda)) as moeda,
        quantidade_equipamentos,
        peso_kg::numeric(12, 2) as peso_kg,
        volume_m3::numeric(10, 2) as volume_m3,
        upper(trim(status)) as status,
        upper(trim(motivo_perda)) as motivo_perda
    from origem
)

select
    cotacao_id, cliente_id, vendedor_id, modal, direcao, rota_codigo, origem, destino,
    solicitada_em, respondida_em, valor_frete, moeda, quantidade_equipamentos,
    peso_kg, volume_m3, status, motivo_perda
from final
