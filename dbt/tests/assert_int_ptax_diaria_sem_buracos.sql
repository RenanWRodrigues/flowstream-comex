-- Regra: int_ptax_diaria tem exatamente 1 linha por dia corrido, de ponta a ponta, até hoje.
-- Falha = alguma moeda com dia faltando (buraco) ou parando antes de hoje.
with dias as (
    select moeda, min(data) as primeiro, max(data) as ultimo, count(*) as linhas
    from {{ ref('int_ptax_diaria') }}
    group by moeda
)

select moeda, primeiro, ultimo, linhas
from dias
where linhas <> (ultimo - primeiro + 1) or ultimo < current_date
