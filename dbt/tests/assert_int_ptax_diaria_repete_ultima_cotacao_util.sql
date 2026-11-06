-- Regra: dia sem PTAX (fim de semana, feriado) usa a última cotação útil anterior.
-- Falha = algum dia com taxa diferente da última PTAX publicada até ele.
with diaria as (
    select moeda, data, cotacao_venda
    from {{ ref('int_ptax_diaria') }}
    where moeda <> 'BRL'
),

ultima_util as (
    select diaria.moeda, diaria.data, diaria.cotacao_venda, anterior.cotacao_venda as esperado
    from diaria
    cross join lateral (
        select ptax.cotacao_venda
        from {{ ref('stg_ptax') }} as ptax
        where ptax.moeda = diaria.moeda and ptax.data_cotacao <= diaria.data
        order by ptax.data_cotacao desc
        limit 1
    ) as anterior
)

select moeda, data, cotacao_venda, esperado
from ultima_util
where cotacao_venda <> esperado
