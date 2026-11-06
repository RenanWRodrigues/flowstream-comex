-- Grão: 1 linha por vendedor e mês da solicitação da cotação.
with cotacoes as (
    select vendedor_id, data_solicitacao, status, ganha
    from {{ ref('fct_cotacao') }}
),

agregado as (
    select
        vendedor_id,
        date_trunc('month', data_solicitacao)::date as mes,
        count(*)::integer as cotacoes,
        count(*) filter (where status <> 'EM_ABERTO')::integer as cotacoes_decididas,
        count(*) filter (where ganha)::integer as cotacoes_ganhas
    from cotacoes
    group by vendedor_id, date_trunc('month', data_solicitacao)
)

select
    vendedor_id,
    mes,
    cotacoes,
    cotacoes_decididas,
    cotacoes_ganhas,
    round(cotacoes_ganhas::numeric / nullif(cotacoes_decididas, 0), 4)::numeric(7, 4)
        as win_rate,
    mes < date_trunc('month', {{ data_de_corte() }})::date as mes_fechado
from agregado
