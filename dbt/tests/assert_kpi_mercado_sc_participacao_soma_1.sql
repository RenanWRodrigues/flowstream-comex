-- Regra: a participação (fração de 0 a 1) soma 1 em cada fluxo e mês, a menos de arredondamento.
select fluxo, mes_referencia, sum(participacao_pct) as soma
from {{ ref('kpi_mercado_sc') }}
group by fluxo, mes_referencia
having abs(sum(participacao_pct) - 1) > 0.001
