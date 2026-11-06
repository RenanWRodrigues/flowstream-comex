{{ config(severity='warn') }}
-- Sanidade da distribuição (aviso, não erro): pontualidade global entre 75% e 85% e
-- demurrage entre 4% e 12% dos FCL de importação chegados. Fora disso, algo mudou nos
-- dados ou no gerador e merece olhar humano.
with medidas as (
    select
        avg(case when chegou_no_prazo then 1.0 else 0 end)
            filter (where chegou_no_prazo is not null) as on_time,
        (select count(distinct processo) from {{ ref('fct_financeiro') }}
            where categoria = 'DEMURRAGE')::numeric
        / nullif(count(*) filter (
            where modal = 'FCL' and direcao = 'IMPORTACAO' and data_ata is not null
        ), 0) as taxa_demurrage
    from {{ ref('fct_embarque') }}
)

select on_time, taxa_demurrage
from medidas
where on_time not between 0.75 and 0.85
    or taxa_demurrage not between 0.04 and 0.12
