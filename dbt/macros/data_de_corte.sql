{#
    Data de corte dos dados: a variável `data_referencia` (AAAA-MM-DD), se informada; senão,
    o dia do último evento de tracking. Os dados sintéticos param em 01/11/2026, então usar
    "hoje" marcaria tudo como atrasado; em produção, informe a data de hoje.

    Usada pelo risco de demurrage e para marcar meses ainda abertos nos KPIs mensais.
#}
{% macro data_de_corte() -%}
    {%- set informada = var('data_referencia', none) -%}
    {%- if informada -%}
        '{{ informada }}'::date
    {%- else -%}
        (select max(data_evento) from {{ ref('fct_tracking_evento') }})
    {%- endif -%}
{%- endmacro %}
