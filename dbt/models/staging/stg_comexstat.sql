-- Grão: 1 linha por fluxo, mês, país, posição SH4 e via (comércio exterior de SC).
with origem as (
    select
        fluxo, ano, mes, pais, sh4_codigo, sh4, via, valor_fob_usd, peso_kg, frete_usd,
        seguro_usd
    from {{ source('bronze', 'comexstat') }}
),

final as (
    select
        upper(trim(fluxo)) as fluxo,
        make_date(ano, mes, 1) as mes_referencia,
        ano,
        mes,
        trim(pais) as pais,
        left(sh4_codigo, 2) as sh2_codigo,
        sh4_codigo,
        trim(sh4) as sh4_descricao,
        upper(trim(via)) as via,
        valor_fob_usd::numeric(16, 2) as valor_fob_usd,
        peso_kg::numeric(16, 2) as peso_kg,
        frete_usd::numeric(16, 2) as frete_usd,
        seguro_usd::numeric(16, 2) as seguro_usd
    from origem
)

select
    fluxo, mes_referencia, ano, mes, pais, sh2_codigo, sh4_codigo, sh4_descricao, via,
    valor_fob_usd, peso_kg, frete_usd, seguro_usd
from final
