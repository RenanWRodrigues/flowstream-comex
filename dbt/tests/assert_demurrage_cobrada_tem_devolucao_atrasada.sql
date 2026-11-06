-- Regra: demurrage cobrada só existe quando o vazio foi devolvido depois do free time, e a
-- devolução de quem não pagou fica dentro dele. Amarra o financeiro ao tracking (achado da
-- auditoria do P06: o risco de demurrage não enxergava a demurrage cobrada).
with free_time as (
    select processo, max(free_time_dias) as dias
    from {{ ref('stg_equipamentos') }}
    group by processo
),

devolucao as (
    select processo, min(ocorrido_em) as devolvido_em
    from {{ ref('fct_tracking_evento') }}
    where tipo = 'DEVOLUCAO_VAZIO'
    group by processo
),

cobrada as (
    select distinct processo
    from {{ ref('fct_financeiro') }}
    where categoria = 'DEMURRAGE'
),

analise as (
    select
        embarques.processo,
        cobrada.processo is not null as pagou_demurrage,
        extract(epoch from devolucao.devolvido_em - embarques.ata) / 86400 as dias_ate_devolver,
        free_time.dias as free_time_dias
    from {{ ref('fct_embarque') }} as embarques
    inner join devolucao on devolucao.processo = embarques.processo
    inner join free_time on free_time.processo = embarques.processo
    left join cobrada on cobrada.processo = embarques.processo
)

select processo, pagou_demurrage, dias_ate_devolver, free_time_dias
from analise
where (pagou_demurrage and dias_ate_devolver <= free_time_dias)
    or (not pagou_demurrage and dias_ate_devolver > free_time_dias)
union all
select cobrada.processo, true, null, null
from cobrada
left join devolucao on devolucao.processo = cobrada.processo
where devolucao.processo is null
