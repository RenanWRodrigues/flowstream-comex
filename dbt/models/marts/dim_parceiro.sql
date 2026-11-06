-- Grão: 1 linha por parceiro de transporte (armador ou companhia aérea).
with armadores as (
    select codigo, nome
    from {{ ref('armadores') }}
),

cias_aereas as (
    select prefixo_awb, nome
    from {{ ref('cias_aereas') }}
),

final as (
    select codigo::text as parceiro_id, nome::text as parceiro_nome, 'ARMADOR' as tipo_parceiro
    from armadores
    union all
    select prefixo_awb::text, nome::text, 'CIA_AEREA'
    from cias_aereas
)

select parceiro_id, parceiro_nome, tipo_parceiro::text as tipo_parceiro
from final
