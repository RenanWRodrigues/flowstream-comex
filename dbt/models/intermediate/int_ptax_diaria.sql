-- Grão: 1 linha por moeda (BRL, USD, EUR) e dia corrido, do primeiro dia com PTAX até hoje.
with ptax as (
    select moeda, data_cotacao, cotacao_compra, cotacao_venda
    from {{ ref('stg_ptax') }}
),

limites as (
    select moeda, min(data_cotacao) as primeiro_dia
    from ptax
    group by moeda
),

calendario as (
    select limites.moeda, dia::date as data
    from limites
    cross join lateral generate_series(limites.primeiro_dia, current_date, interval '1 day') as dia
),

com_grupo as (
    -- Cada dia útil abre um grupo; os dias seguintes sem PTAX ficam no mesmo grupo.
    select
        calendario.moeda,
        calendario.data,
        ptax.cotacao_compra,
        ptax.cotacao_venda,
        ptax.data_cotacao,
        count(ptax.data_cotacao) over (
            partition by calendario.moeda order by calendario.data
        ) as grupo
    from calendario
    left join ptax
        on ptax.moeda = calendario.moeda and ptax.data_cotacao = calendario.data
),

preenchido as (
    select
        moeda,
        data,
        first_value(cotacao_compra) over janela as cotacao_compra,
        first_value(cotacao_venda) over janela as cotacao_venda,
        first_value(data_cotacao) over janela as data_cotacao_ptax
    from com_grupo
    window janela as (partition by moeda, grupo order by data)
),

estrangeiras as (
    select
        moeda,
        data,
        cotacao_compra,
        cotacao_venda,
        data_cotacao_ptax,
        data = data_cotacao_ptax as dia_com_ptax
    from preenchido
    where data_cotacao_ptax is not null
),

real_brasileiro as (
    select
        'BRL'::text as moeda,
        dia::date as data,
        1::numeric(12, 6) as cotacao_compra,
        1::numeric(12, 6) as cotacao_venda,
        dia::date as data_cotacao_ptax,
        true as dia_com_ptax
    from generate_series(
        (select min(primeiro_dia) from limites), current_date, interval '1 day'
    ) as dia
),

final as (
    select moeda, data, cotacao_compra, cotacao_venda, data_cotacao_ptax, dia_com_ptax
    from estrangeiras
    union all
    select moeda, data, cotacao_compra, cotacao_venda, data_cotacao_ptax, dia_com_ptax
    from real_brasileiro
)

select moeda, data, cotacao_compra, cotacao_venda, data_cotacao_ptax, dia_com_ptax
from final
