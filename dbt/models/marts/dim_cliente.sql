-- Grão: 1 linha por versão do cliente (SCD tipo 2, a partir do snapshot snap_clientes).
with versoes as (
    select
        dbt_scd_id, cliente_id, cnpj, razao_social, segmento, porte, uf, vendedor_id,
        data_cadastro, dbt_valid_from, dbt_valid_to
    from {{ ref('snap_clientes') }}
),

segmentos as (
    select codigo, nome
    from {{ ref('segmentos') }}
),

numeradas as (
    select
        versoes.dbt_scd_id,
        versoes.cliente_id,
        versoes.cnpj,
        versoes.razao_social,
        versoes.segmento,
        versoes.porte,
        versoes.uf,
        versoes.vendedor_id,
        versoes.data_cadastro,
        versoes.dbt_valid_from,
        versoes.dbt_valid_to,
        row_number() over (
            partition by versoes.cliente_id order by versoes.dbt_valid_from
        ) as numero_versao
    from versoes
),

final as (
    select
        numeradas.dbt_scd_id as cliente_sk,
        numeradas.cliente_id,
        numeradas.cnpj,
        numeradas.razao_social,
        numeradas.segmento,
        segmentos.nome as segmento_nome,
        numeradas.porte,
        numeradas.uf,
        numeradas.vendedor_id,
        numeradas.data_cadastro,
        -- A 1ª versão vale desde sempre: o snapshot só começou a observar depois.
        case
            when numeradas.numero_versao = 1 then '-infinity'::timestamptz
            else numeradas.dbt_valid_from::timestamptz
        end as valido_de,
        numeradas.dbt_valid_to::timestamptz as valido_ate,
        numeradas.dbt_valid_to is null as versao_atual
    from numeradas
    left join segmentos on segmentos.codigo = numeradas.segmento
)

select
    cliente_sk, cliente_id, cnpj, razao_social, segmento, segmento_nome, porte, uf,
    vendedor_id, data_cadastro, valido_de, valido_ate, versao_atual
from final
