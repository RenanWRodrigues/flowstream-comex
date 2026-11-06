-- Grão: 1 linha por processo de embarque, com prazos, atrasos e pontualidade em dias.
with embarques as (
    select
        processo, modal, direcao, rota_codigo, armador_codigo, status,
        booking_em, etd, eta, atd, ata
    from {{ ref('stg_embarques') }}
),

rotas as (
    select codigo, transit_time_medio_dias
    from {{ ref('rotas') }}
),

calculado as (
    select
        embarques.processo,
        embarques.modal,
        embarques.direcao,
        embarques.rota_codigo,
        embarques.armador_codigo,
        embarques.status,
        embarques.booking_em,
        embarques.etd,
        embarques.eta,
        embarques.atd,
        embarques.ata,
        round((extract(epoch from embarques.eta - embarques.etd) / 86400)::numeric, 2)
            as transit_previsto_dias,
        round((extract(epoch from embarques.ata - embarques.atd) / 86400)::numeric, 2)
            as transit_real_dias,
        round((extract(epoch from embarques.atd - embarques.etd) / 86400)::numeric, 2)
            as atraso_saida_dias,
        round((extract(epoch from embarques.ata - embarques.eta) / 86400)::numeric, 2)
            as atraso_chegada_dias,
        case
            when embarques.ata is null then null
            else embarques.ata <= embarques.eta + interval '1 day'
        end as chegou_no_prazo,
        {{ dias_uteis_entre('embarques.booking_em', 'embarques.etd') }} as dias_uteis_booking_etd,
        rotas.transit_time_medio_dias as transit_rota_dias
    from embarques
    left join rotas on rotas.codigo = embarques.rota_codigo
)

select
    processo, modal, direcao, rota_codigo, armador_codigo, status,
    booking_em, etd, eta, atd, ata,
    transit_previsto_dias, transit_real_dias, atraso_saida_dias, atraso_chegada_dias,
    chegou_no_prazo, dias_uteis_booking_etd, transit_rota_dias
from calculado
