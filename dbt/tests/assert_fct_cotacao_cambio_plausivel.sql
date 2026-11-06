-- Regra: a conversão do frete cotado é plausível: BRL vale 1; USD e EUR entre R$ 3,50 e
-- R$ 9,00 (faixa ampla em torno de 2024-2026). Fora disso, PTAX ou moeda trocada.
select cotacao_id, moeda, valor_frete, valor_frete_brl,
    valor_frete_brl / nullif(valor_frete, 0) as taxa_implicita
from {{ ref('fct_cotacao') }}
where valor_frete > 0
    and (
        (moeda = 'BRL' and valor_frete_brl <> valor_frete)
        or (moeda <> 'BRL' and valor_frete_brl / valor_frete not between 3.5 and 9)
    )
