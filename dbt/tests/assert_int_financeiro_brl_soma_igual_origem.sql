-- Regra: a conversão não perde nem duplica itens. Por moeda, a quantidade de itens e a soma
-- na moeda original de int_financeiro_brl são iguais às do staging.
with origem as (
    select moeda, count(*) as itens, sum(valor) as total
    from {{ ref('stg_itens_financeiros') }}
    group by moeda
),

convertido as (
    select moeda, count(*) as itens, sum(valor_original) as total
    from {{ ref('int_financeiro_brl') }}
    group by moeda
)

select
    coalesce(origem.moeda, convertido.moeda) as moeda,
    origem.itens as itens_origem,
    convertido.itens as itens_convertido,
    origem.total as total_origem,
    convertido.total as total_convertido
from origem
full outer join convertido on convertido.moeda = origem.moeda
where origem.itens is distinct from convertido.itens
    or origem.total is distinct from convertido.total
