{#
    Dias úteis depois de `inicio` até `fim`, inclusive: segunda a sexta, menos os feriados
    nacionais e bancários do seed `feriados` (os mesmos dias em que não há PTAX).

    Exemplos: sexta -> segunda = 1; segunda -> sexta = 4; mesmo dia = 0;
    `fim` antes de `inicio` = 0; quinta 17/04/2025 -> terça 22/04 = 1 (Sexta Santa e
    Tiradentes no meio).

    Uso: {{ dias_uteis_entre('booking_em', 'etd') }} -> integer.
#}
{% macro dias_uteis_entre(inicio, fim) -%}
    (
        select count(*)::integer
        from generate_series(
            ({{ inicio }})::date + 1, ({{ fim }})::date, interval '1 day'
        ) as dia
        where extract(isodow from dia) < 6
            and not exists (
                select 1 from {{ ref('feriados') }} as feriado where feriado.data = dia::date
            )
    )
{%- endmacro %}
