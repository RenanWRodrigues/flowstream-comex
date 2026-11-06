-- Grão: 1 linha por modal e mês da solicitação da cotação.
with cotacoes as (
    select modal, data_solicitacao, tempo_resposta_horas
    from {{ ref('fct_cotacao') }}
),

agregado as (
    select
        modal,
        date_trunc('month', data_solicitacao)::date as mes,
        count(*)::integer as cotacoes,
        avg(tempo_resposta_horas) as media,
        percentile_cont(0.5) within group (order by tempo_resposta_horas) as mediana,
        percentile_cont(0.9) within group (order by tempo_resposta_horas) as p90,
        count(*) filter (where tempo_resposta_horas <= 24) as ate_24h
    from cotacoes
    group by modal, date_trunc('month', data_solicitacao)
)

select
    modal,
    mes,
    cotacoes,
    round(media, 2)::numeric(10, 2) as tempo_medio_horas,
    round(mediana::numeric, 2)::numeric(10, 2) as tempo_mediano_horas,
    round(p90::numeric, 2)::numeric(10, 2) as tempo_p90_horas,
    round(ate_24h::numeric / cotacoes, 4)::numeric(7, 4) as pct_respondidas_24h,
    mes < date_trunc('month', {{ data_de_corte() }})::date as mes_fechado
from agregado
