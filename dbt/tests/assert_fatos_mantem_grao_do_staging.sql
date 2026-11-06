-- Regra: os joins dos fatos (inclusive com as versões SCD2 do cliente) não multiplicam nem
-- perdem linhas: cada fato tem exatamente as linhas do staging de origem.
with contagens as (
    select 'fct_embarque' as fato,
        (select count(*) from {{ ref('fct_embarque') }}) as linhas_fato,
        (select count(*) from {{ ref('stg_embarques') }}) as linhas_origem
    union all
    select 'fct_cotacao',
        (select count(*) from {{ ref('fct_cotacao') }}),
        (select count(*) from {{ ref('stg_cotacoes') }})
    union all
    select 'fct_financeiro',
        (select count(*) from {{ ref('fct_financeiro') }}),
        (select count(*) from {{ ref('stg_itens_financeiros') }})
    union all
    select 'fct_tracking_evento',
        (select count(*) from {{ ref('fct_tracking_evento') }}),
        (select count(*) from {{ ref('stg_tracking') }})
)

select fato, linhas_fato, linhas_origem
from contagens
where linhas_fato <> linhas_origem
