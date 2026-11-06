-- Grão: 1 linha por fluxo, mês, país e capítulo SH2 (comércio exterior de SC, Comex Stat).
with comex as (
    select fluxo, mes_referencia, pais, sh2_codigo, valor_fob_usd, peso_kg, frete_usd
    from {{ ref('stg_comexstat') }}
),

agregado as (
    select
        fluxo,
        mes_referencia,
        pais,
        sh2_codigo,
        sum(valor_fob_usd) as valor_fob_usd,
        sum(peso_kg) as peso_kg,
        sum(frete_usd) as frete_usd
    from comex
    group by fluxo, mes_referencia, pais, sh2_codigo
)

select
    fluxo,
    mes_referencia,
    pais,
    sh2_codigo,
    valor_fob_usd::numeric(18, 2) as valor_fob_usd,
    peso_kg::numeric(18, 2) as peso_kg,
    frete_usd::numeric(18, 2) as frete_usd,
    round(
        valor_fob_usd / nullif(sum(valor_fob_usd) over (partition by fluxo, mes_referencia), 0),
        6
    )::numeric(9, 6) as participacao_pct
from agregado
