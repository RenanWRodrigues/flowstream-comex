-- Grão: 1 linha por vendedor.
with vendedores as (
    select vendedor_id, vendedor_nome, data_admissao
    from {{ ref('stg_vendedores') }}
)

select vendedor_id, vendedor_nome, data_admissao
from vendedores
