-- Grão: 1 linha por dia, de 2023-01-01 a 2027-12-31.
with dias as (
    select dia::date as data
    from generate_series('2023-01-01'::date, '2027-12-31'::date, interval '1 day') as dia
),

feriados as (
    select data, nome, tipo
    from {{ ref('feriados') }}
),

calendario as (
    select
        dias.data,
        extract(year from dias.data)::integer as ano,
        extract(quarter from dias.data)::integer as trimestre,
        extract(month from dias.data)::integer as mes,
        extract(day from dias.data)::integer as dia,
        to_char(dias.data, 'YYYY-MM') as ano_mes,
        date_trunc('month', dias.data)::date as inicio_mes,
        (array[
            'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
            'setembro', 'outubro', 'novembro', 'dezembro'
        ])[extract(month from dias.data)::integer] as nome_mes,
        extract(isodow from dias.data)::integer as dia_semana,
        (array[
            'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira',
            'sábado', 'domingo'
        ])[extract(isodow from dias.data)::integer] as nome_dia_semana,
        extract(isodow from dias.data) >= 6 as eh_fim_de_semana,
        feriados.data is not null as eh_feriado,
        feriados.nome as nome_feriado,
        feriados.tipo as tipo_feriado
    from dias
    left join feriados on feriados.data = dias.data
),

final as (
    select
        data, ano, trimestre, mes, dia, ano_mes, inicio_mes, nome_mes, dia_semana,
        nome_dia_semana, eh_fim_de_semana, eh_feriado, nome_feriado, tipo_feriado,
        not eh_fim_de_semana and not eh_feriado as eh_dia_util
    from calendario
)

select
    data, ano, trimestre, mes, dia, ano_mes, inicio_mes, nome_mes, dia_semana,
    nome_dia_semana, eh_fim_de_semana, eh_feriado, nome_feriado, tipo_feriado, eh_dia_util
from final
