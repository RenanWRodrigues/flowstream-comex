-- Grão: 1 linha por rota operada.
with rotas as (
    select
        codigo, modal, trade_lane, origem, destino, transit_time_medio_dias,
        transit_time_desvio_dias
    from {{ ref('rotas') }}
),

locais as (
    select local_codigo, local_nome, pais_iso2
    from {{ ref('dim_porto') }}
),

final as (
    select
        rotas.codigo::text as rota_codigo,
        rotas.modal::text as modal,
        rotas.trade_lane::text as trade_lane,
        case when origem.pais_iso2 = 'BR' then 'EXPORTACAO' else 'IMPORTACAO' end as direcao,
        rotas.origem::text as origem,
        origem.local_nome as origem_nome,
        rotas.destino::text as destino,
        destino.local_nome as destino_nome,
        rotas.transit_time_medio_dias::numeric(5, 1) as transit_time_medio_dias,
        rotas.transit_time_desvio_dias::numeric(5, 1) as transit_time_desvio_dias
    from rotas
    left join locais as origem on origem.local_codigo = rotas.origem
    left join locais as destino on destino.local_codigo = rotas.destino
)

select
    rota_codigo, modal, trade_lane, direcao, origem, origem_nome, destino, destino_nome,
    transit_time_medio_dias, transit_time_desvio_dias
from final
