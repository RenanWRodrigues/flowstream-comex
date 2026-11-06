-- Regra (SCD2): cada cliente tem exatamente 1 versão atual, e as versões não se sobrepõem
-- (cada uma começa onde a anterior terminou).
with versoes as (
    select
        cliente_id,
        valido_de,
        valido_ate,
        versao_atual,
        lag(valido_ate) over (partition by cliente_id order by valido_de) as fim_anterior,
        row_number() over (partition by cliente_id order by valido_de) as numero
    from {{ ref('dim_cliente') }}
),

atuais as (
    select cliente_id, count(*) filter (where versao_atual) as versoes_atuais
    from versoes
    group by cliente_id
)

select versoes.cliente_id, 'sobreposição ou buraco' as problema
from versoes
where versoes.numero > 1 and versoes.valido_de is distinct from versoes.fim_anterior
union all
select cliente_id, 'versões atuais: ' || versoes_atuais
from atuais
where versoes_atuais <> 1
