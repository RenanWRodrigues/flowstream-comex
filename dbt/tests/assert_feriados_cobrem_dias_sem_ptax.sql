-- Regra: todo dia de semana em que o Banco Central não publicou PTAX precisa estar no seed
-- `feriados` (confere a lista de feriados contra a fonte real). Falha = feriado faltando.
with dias as (
    select dia::date as data
    from generate_series(
        (select min(data_cotacao) from {{ ref('stg_ptax') }}),
        (select max(data_cotacao) from {{ ref('stg_ptax') }}),
        interval '1 day'
    ) as dia
    where extract(isodow from dia) < 6
),

sem_ptax as (
    select dias.data
    from dias
    left join {{ ref('stg_ptax') }} as ptax
        on ptax.moeda = 'USD' and ptax.data_cotacao = dias.data
    where ptax.data_cotacao is null
)

select sem_ptax.data
from sem_ptax
left join {{ ref('feriados') }} as feriados on feriados.data = sem_ptax.data
where feriados.data is null
