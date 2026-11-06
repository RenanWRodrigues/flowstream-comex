-- Grão: 1 linha por cliente.
with origem as (
    select cliente_id, cnpj, razao_social, segmento, porte, uf, vendedor_id, data_cadastro
    from {{ source('bronze', 'clientes') }}
),

final as (
    select
        upper(trim(cliente_id)) as cliente_id,
        upper(regexp_replace(cnpj, '[^0-9A-Za-z]', '', 'g')) as cnpj,
        trim(razao_social) as razao_social,
        upper(trim(segmento)) as segmento,
        upper(trim(porte)) as porte,
        upper(trim(uf)) as uf,
        upper(trim(vendedor_id)) as vendedor_id,
        data_cadastro
    from origem
)

select cliente_id, cnpj, razao_social, segmento, porte, uf, vendedor_id, data_cadastro
from final
