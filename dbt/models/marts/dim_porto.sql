-- Grão: 1 linha por local (porto por UN/LOCODE ou aeroporto por IATA).
with portos as (
    select unlocode, nome, pais_iso2, regiao
    from {{ ref('portos') }}
),

aeroportos as (
    select iata, nome, cidade, pais_iso2
    from {{ ref('aeroportos') }}
),

paises as (
    select iso2, nome, regiao
    from {{ ref('paises') }}
),

locais as (
    select
        portos.unlocode as local_codigo,
        portos.nome as local_nome,
        'PORTO' as tipo_local,
        portos.nome as cidade,
        portos.pais_iso2,
        portos.regiao
    from portos
    union all
    select
        aeroportos.iata,
        aeroportos.nome,
        'AEROPORTO',
        aeroportos.cidade,
        aeroportos.pais_iso2,
        paises.regiao
    from aeroportos
    left join paises on paises.iso2 = aeroportos.pais_iso2
),

final as (
    select
        locais.local_codigo::text as local_codigo,
        locais.local_nome::text as local_nome,
        locais.tipo_local::text as tipo_local,
        locais.cidade::text as cidade,
        locais.pais_iso2::text as pais_iso2,
        paises.nome::text as pais_nome,
        locais.regiao::text as regiao
    from locais
    left join paises on paises.iso2 = locais.pais_iso2
)

select local_codigo, local_nome, tipo_local, cidade, pais_iso2, pais_nome, regiao
from final
