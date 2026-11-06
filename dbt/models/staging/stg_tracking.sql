-- Grão: 1 linha por evento de rastreamento.
with origem as (
    select evento_id, processo, tipo, ocorrido_em, local, eta_informada
    from {{ source('bronze', 'tracking_eventos') }}
),

final as (
    select
        upper(trim(evento_id)) as evento_id,
        upper(trim(processo)) as processo,
        upper(trim(tipo)) as tipo,
        ocorrido_em,
        upper(replace(local, ' ', '')) as local,
        eta_informada
    from origem
)

select evento_id, processo, tipo, ocorrido_em, local, eta_informada
from final
