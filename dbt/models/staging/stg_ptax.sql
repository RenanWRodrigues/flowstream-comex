-- Grão: 1 linha por moeda e dia útil (PTAX de fechamento do Banco Central).
with origem as (
    select
        moeda, data_cotacao, cotacao_compra, cotacao_venda, paridade_compra, paridade_venda,
        data_hora_cotacao
    from {{ source('bronze', 'ptax') }}
),

final as (
    select
        upper(trim(moeda)) as moeda,
        data_cotacao,
        cotacao_compra::numeric(12, 6) as cotacao_compra,
        cotacao_venda::numeric(12, 6) as cotacao_venda,
        paridade_compra::numeric(12, 6) as paridade_compra,
        paridade_venda::numeric(12, 6) as paridade_venda,
        data_hora_cotacao
    from origem
)

select
    moeda, data_cotacao, cotacao_compra, cotacao_venda, paridade_compra, paridade_venda,
    data_hora_cotacao
from final
