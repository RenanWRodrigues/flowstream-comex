-- Testa a macro dias_uteis_entre com casos conhecidos (2025).
-- 03/01 é sexta, 06/01 é segunda, 10/01 é sexta, 13/01 é segunda.
with casos as (
    select 'sexta a segunda' as caso,
        {{ dias_uteis_entre("'2025-01-03'::date", "'2025-01-06'::date") }} as obtido, 1 as esperado
    union all
    select 'segunda a sexta',
        {{ dias_uteis_entre("'2025-01-06'::date", "'2025-01-10'::date") }}, 4
    union all
    select 'segunda a segunda',
        {{ dias_uteis_entre("'2025-01-06'::date", "'2025-01-13'::date") }}, 5
    union all
    select 'mesmo dia',
        {{ dias_uteis_entre("'2025-01-06'::date", "'2025-01-06'::date") }}, 0
    union all
    select 'sábado a domingo',
        {{ dias_uteis_entre("'2025-01-04'::date", "'2025-01-05'::date") }}, 0
    union all
    select 'fim antes do início',
        {{ dias_uteis_entre("'2025-01-10'::date", "'2025-01-06'::date") }}, 0
    union all
    -- 18/04/2025 Sexta-feira Santa e 21/04 Tiradentes: só 22/04 é útil.
    select 'desconta feriados',
        {{ dias_uteis_entre("'2025-04-17'::date", "'2025-04-22'::date") }}, 1
    union all
    select 'carnaval é feriado bancário',
        {{ dias_uteis_entre("'2025-02-28'::date", "'2025-03-05'::date") }}, 1
    union all
    select 'aceita timestamp com fuso',
        {{ dias_uteis_entre("'2025-01-03 18:00-03'::timestamptz", "'2025-01-06 08:00-03'::timestamptz") }}, 1
)

select caso, obtido, esperado
from casos
where obtido <> esperado
