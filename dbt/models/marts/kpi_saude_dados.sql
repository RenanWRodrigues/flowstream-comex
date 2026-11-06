-- Grão: 1 linha por dia com flowstream quality run (vale a última execução do dia).
with resultados as (
    select run_id, executado_em, tipo, status
    from {{ source('ops', 'dq_results') }}
),

anomalias as (
    select run_id, count(*) as quantidade
    from {{ source('ops', 'dq_anomalias') }}
    group by run_id
),

execucoes as (
    select run_id, (max(executado_em) at time zone 'America/Sao_Paulo')::date as data
    from resultados
    group by run_id
),

ultima_do_dia as (
    select distinct on (data) data, run_id
    from execucoes
    order by data, run_id desc
),

contagens as (
    select
        ultima_do_dia.data,
        ultima_do_dia.run_id,
        count(*) filter (where resultados.tipo = 'test' and resultados.status = 'pass')
            as testes_ok,
        count(*) filter (where resultados.tipo = 'test' and resultados.status = 'warn')
            as testes_aviso,
        count(*) filter (
            where resultados.tipo = 'test' and resultados.status in ('fail', 'error')
        ) as testes_falha,
        count(*) filter (
            where resultados.tipo not in ('test', 'freshness') and resultados.status = 'error'
        ) as recursos_com_erro,
        count(*) filter (
            where resultados.tipo = 'freshness'
                and resultados.status in ('warn', 'error', 'runtime error')
        ) as fontes_atrasadas
    from ultima_do_dia
    inner join resultados on resultados.run_id = ultima_do_dia.run_id
    group by ultima_do_dia.data, ultima_do_dia.run_id
),

final as (
    select
        contagens.data,
        contagens.run_id,
        contagens.testes_ok::integer as testes_ok,
        contagens.testes_aviso::integer as testes_aviso,
        contagens.testes_falha::integer as testes_falha,
        contagens.recursos_com_erro::integer as recursos_com_erro,
        contagens.fontes_atrasadas::integer as fontes_atrasadas,
        coalesce(anomalias.quantidade, 0)::integer as anomalias,
        round(
            contagens.testes_ok::numeric
            / nullif(contagens.testes_ok + contagens.testes_aviso + contagens.testes_falha, 0),
            4
        )::numeric(7, 4) as pct_testes_ok,
        contagens.testes_falha = 0 and contagens.recursos_com_erro = 0 as saudavel
    from contagens
    left join anomalias on anomalias.run_id = contagens.run_id
)

select
    data, run_id, testes_ok, testes_aviso, testes_falha, recursos_com_erro, fontes_atrasadas,
    anomalias, pct_testes_ok, saudavel
from final
