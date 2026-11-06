-- Regra (guia): nenhum embarque sem dim_data. Toda data preenchida do processo (booking,
-- ETD, ETA, ATD, ATA) precisa existir no calendário.
with datas as (
    select processo, 'booking' as marco, data_booking as data from {{ ref('fct_embarque') }}
    union all
    select processo, 'etd', data_etd from {{ ref('fct_embarque') }}
    union all
    select processo, 'eta', data_eta from {{ ref('fct_embarque') }}
    union all
    select processo, 'atd', data_atd from {{ ref('fct_embarque') }} where data_atd is not null
    union all
    select processo, 'ata', data_ata from {{ ref('fct_embarque') }} where data_ata is not null
)

select datas.processo, datas.marco, datas.data
from datas
left join {{ ref('dim_data') }} as calendario on calendario.data = datas.data
where calendario.data is null
