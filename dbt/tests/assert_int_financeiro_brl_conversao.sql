-- Regra: BRL não muda de valor; moeda estrangeira = valor x PTAX de venda, em 2 casas.
select item_id, moeda, valor_original, taxa_cambio, valor_brl
from {{ ref('int_financeiro_brl') }}
where (moeda = 'BRL' and valor_brl <> valor_original)
    or (moeda <> 'BRL' and valor_brl <> round(valor_original * taxa_cambio, 2))
