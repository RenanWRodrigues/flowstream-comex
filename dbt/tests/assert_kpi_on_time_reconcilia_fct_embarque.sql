-- Regra: o KPI de pontualidade bate, por armador e mês, com a contagem feita direto no fato.
with fato as (
    select
        armador_codigo,
        date_trunc('month', data_ata)::date as mes,
        count(*) as chegados,
        count(*) filter (where chegou_no_prazo) as no_prazo
    from {{ ref('fct_embarque') }}
    where armador_codigo is not null and data_ata is not null
    group by 1, 2
)

select coalesce(kpi.armador_codigo, fato.armador_codigo) as armador_codigo, fato.mes
from {{ ref('kpi_on_time_armador_mes') }} as kpi
full outer join fato on fato.armador_codigo = kpi.armador_codigo and fato.mes = kpi.mes
where kpi.embarques_chegados is distinct from fato.chegados
    or kpi.embarques_no_prazo is distinct from fato.no_prazo
