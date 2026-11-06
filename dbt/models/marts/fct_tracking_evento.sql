-- Grão: 1 linha por evento de rastreamento.
with eventos as (
    select evento_id, processo, tipo, ocorrido_em, local, eta_informada
    from {{ ref('stg_tracking') }}
),

embarques as (
    select processo, eta
    from {{ ref('stg_embarques') }}
),

final as (
    select
        eventos.evento_id,
        eventos.processo,
        eventos.tipo,
        (eventos.ocorrido_em at time zone 'America/Sao_Paulo')::date as data_evento,
        eventos.ocorrido_em,
        eventos.local as local_codigo,
        embarques.eta as eta_original,
        eventos.eta_informada,
        round(
            (extract(epoch from eventos.eta_informada - embarques.eta) / 3600)::numeric, 2
        )::numeric(10, 2) as variacao_eta_horas
    from eventos
    left join embarques on embarques.processo = eventos.processo
)

select
    evento_id, processo, tipo, data_evento, ocorrido_em, local_codigo, eta_original,
    eta_informada, variacao_eta_horas
from final
