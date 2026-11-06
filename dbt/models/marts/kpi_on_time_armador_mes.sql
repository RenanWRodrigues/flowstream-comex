-- Grão: 1 linha por armador e mês da chegada (ATA).
with chegados as (
    select armador_codigo, data_ata, chegou_no_prazo, atraso_chegada_dias
    from {{ ref('fct_embarque') }}
    where armador_codigo is not null and data_ata is not null
),

agregado as (
    select
        armador_codigo,
        date_trunc('month', data_ata)::date as mes,
        count(*)::integer as embarques_chegados,
        count(*) filter (where chegou_no_prazo)::integer as embarques_no_prazo,
        avg(atraso_chegada_dias) as atraso_medio
    from chegados
    group by armador_codigo, date_trunc('month', data_ata)
)

select
    armador_codigo,
    mes,
    embarques_chegados,
    embarques_no_prazo,
    round(embarques_no_prazo::numeric / embarques_chegados, 4)::numeric(7, 4) as pct_on_time,
    round(atraso_medio, 2)::numeric(8, 2) as atraso_medio_dias,
    mes < date_trunc('month', {{ data_de_corte() }})::date as mes_fechado
from agregado
