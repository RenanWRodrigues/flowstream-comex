-- Grão: 1 linha por contêiner de importação chegado e ainda não devolvido, na data de corte.
with referencia as (
    select {{ data_de_corte() }} as data_referencia
),

equipamentos as (
    select processo, container_numero, tipo, free_time_dias
    from {{ ref('stg_equipamentos') }}
),

embarques as (
    select processo, cliente_id, armador_codigo, destino, data_ata
    from {{ ref('fct_embarque') }}
    where direcao = 'IMPORTACAO' and data_ata is not null
),

devolucoes as (
    select processo, min(data_evento) as data_devolucao
    from {{ ref('fct_tracking_evento') }}
    where tipo = 'DEVOLUCAO_VAZIO'
    group by processo
),

calculado as (
    select
        equipamentos.processo,
        equipamentos.container_numero,
        equipamentos.tipo,
        embarques.cliente_id,
        embarques.armador_codigo,
        embarques.destino,
        embarques.data_ata,
        equipamentos.free_time_dias,
        referencia.data_referencia,
        (referencia.data_referencia - embarques.data_ata)::integer as dias_desde_ata,
        devolucoes.data_devolucao
    from equipamentos
    inner join embarques on embarques.processo = equipamentos.processo
    left join devolucoes on devolucoes.processo = equipamentos.processo
    cross join referencia
),

final as (
    select
        processo, container_numero, tipo, cliente_id, armador_codigo, destino, data_ata,
        free_time_dias, data_referencia, dias_desde_ata,
        free_time_dias - dias_desde_ata as dias_livres_restantes,
        case
            when free_time_dias - dias_desde_ata < 0 then 'VENCIDO'
            when free_time_dias - dias_desde_ata <= 3 then 'CRITICO'
            when free_time_dias - dias_desde_ata <= 7 then 'ATENCAO'
            else 'OK'
        end as faixa_risco
    from calculado
    -- Em aberto: já chegou e o vazio ainda não foi devolvido até a data de corte.
    where dias_desde_ata >= 0
        and (data_devolucao is null or data_devolucao > data_referencia)
)

select
    processo, container_numero, tipo, cliente_id, armador_codigo, destino, data_ata,
    free_time_dias, data_referencia, dias_desde_ata, dias_livres_restantes, faixa_risco
from final
