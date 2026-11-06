-- Regra (guia): receita - custos = margem em kpi_margem_processo, conferida contra uma fonte
-- independente: a soma dos valores assinados (receita +, custo -) em fct_financeiro.
with financeiro as (
    select processo, sum(valor_brl_assinado) as margem_esperada
    from {{ ref('fct_financeiro') }}
    group by processo
)

select kpi.processo, kpi.receita_brl, kpi.custo_brl, kpi.margem_brl, financeiro.margem_esperada
from {{ ref('kpi_margem_processo') }} as kpi
full outer join financeiro on financeiro.processo = kpi.processo
where kpi.processo is null
    or financeiro.processo is null
    or kpi.receita_brl - kpi.custo_brl <> kpi.margem_brl
    or kpi.margem_brl <> financeiro.margem_esperada
