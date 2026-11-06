-- Grão: 1 linha por contêiner ou isotanque de um processo.
with origem as (
    select processo, numero, tipo, peso_kg, free_time_dias
    from {{ source('bronze', 'equipamentos') }}
),

final as (
    select
        upper(trim(processo)) as processo,
        upper(replace(numero, ' ', '')) as container_numero,
        upper(trim(tipo)) as tipo,
        peso_kg::numeric(12, 2) as peso_kg,
        free_time_dias
    from origem
)

select processo, container_numero, tipo, peso_kg, free_time_dias
from final
