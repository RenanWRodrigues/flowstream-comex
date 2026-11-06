-- Grão: 1 linha por processo já embarcado (com itens financeiros).
with itens as (
    select processo, tipo, categoria, valor_brl
    from {{ ref('fct_financeiro') }}
),

embarques as (
    select processo, cliente_id, modal, direcao, data_atd
    from {{ ref('fct_embarque') }}
),

por_processo as (
    select
        processo,
        sum(valor_brl) filter (where tipo = 'RECEITA') as receita_brl,
        sum(valor_brl) filter (where tipo = 'CUSTO') as custo_brl,
        bool_or(categoria = 'DEMURRAGE') as teve_demurrage,
        bool_or(categoria = 'DEMURRAGE' and tipo = 'CUSTO')
            and not bool_or(categoria = 'DEMURRAGE' and tipo = 'RECEITA') as demurrage_absorvida
    from itens
    group by processo
),

final as (
    select
        por_processo.processo,
        embarques.cliente_id,
        embarques.modal,
        embarques.direcao,
        embarques.data_atd,
        coalesce(por_processo.receita_brl, 0)::numeric(16, 2) as receita_brl,
        coalesce(por_processo.custo_brl, 0)::numeric(16, 2) as custo_brl,
        (coalesce(por_processo.receita_brl, 0) - coalesce(por_processo.custo_brl, 0))::numeric(
            16, 2
        ) as margem_brl,
        round(
            (por_processo.receita_brl - coalesce(por_processo.custo_brl, 0))
            / nullif(por_processo.receita_brl, 0),
            4
        )::numeric(7, 4) as margem_pct,
        por_processo.teve_demurrage,
        por_processo.demurrage_absorvida
    from por_processo
    left join embarques on embarques.processo = por_processo.processo
)

select
    processo, cliente_id, modal, direcao, data_atd, receita_brl, custo_brl, margem_brl,
    margem_pct, teve_demurrage, demurrage_absorvida
from final
