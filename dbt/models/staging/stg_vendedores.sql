-- Grão: 1 linha por vendedor.
with origem as (
    select vendedor_id, nome, data_admissao
    from {{ source('bronze', 'vendedores') }}
),

final as (
    select
        upper(trim(vendedor_id)) as vendedor_id,
        trim(nome) as vendedor_nome,
        data_admissao
    from origem
)

select vendedor_id, vendedor_nome, data_admissao
from final
