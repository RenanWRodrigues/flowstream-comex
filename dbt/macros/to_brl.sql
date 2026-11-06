{#
    Converte `valor` em `moeda` para BRL pela PTAX de venda da `data` (dia corrido).

    Fins de semana e feriados usam a última PTAX útil (int_ptax_diaria). BRL vale 1.
    Moeda sem PTAX (ex.: CNY) devolve NULL, de propósito: o teste not_null do modelo que
    usa a macro acusa o problema em vez de esconder um valor errado.

    Uso: {{ to_brl('valor', 'moeda', 'competencia') }} -> numeric com 2 casas.
#}
{% macro to_brl(valor, moeda, data) -%}
    round(
        ({{ valor }}) * (
            select ptax.cotacao_venda
            from {{ ref('int_ptax_diaria') }} as ptax
            where ptax.moeda = ({{ moeda }}) and ptax.data = ({{ data }})::date
        ),
        2
    )
{%- endmacro %}
