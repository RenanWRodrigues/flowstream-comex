-- Testa a macro to_brl: BRL vale 1; USD usa a PTAX de venda do dia; sábado usa a de sexta;
-- moeda sem PTAX (CNY) dá NULL. Só roda quando a PTAX de jan/2025 está carregada.
with sexta as (
    select cotacao_venda
    from {{ ref('stg_ptax') }}
    where moeda = 'USD' and data_cotacao = '2025-01-03'
),

casos as (
    select 'BRL vale 1' as caso,
        {{ to_brl('100', "'BRL'", "'2025-01-03'") }} as obtido,
        100.00::numeric as esperado
    union all
    select 'USD em dia útil',
        {{ to_brl('100', "'USD'", "'2025-01-03'") }},
        round(100 * (select cotacao_venda from sexta), 2)
    union all
    select 'USD no sábado usa a sexta',
        {{ to_brl('100', "'USD'", "'2025-01-04'") }},
        round(100 * (select cotacao_venda from sexta), 2)
    union all
    select 'CNY sem PTAX é nulo',
        {{ to_brl('100', "'CNY'", "'2025-01-03'") }},
        null
)

select caso, obtido, esperado
from casos
where exists (select 1 from sexta)
    and obtido is distinct from esperado
