{#
    Usa o schema customizado exatamente como configurado (prata, ouro), em vez do padrão
    do dbt, que concatenaria com o schema do profile (ex.: prata_ouro).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
