-- Regra: demurrage só existe em FCL de importação (no Brasil, quem paga é o importador; na
-- exportação, é o comprador no destino). Achado da auditoria de dados do P03.
select financeiro.item_id, financeiro.processo, embarques.modal, embarques.direcao
from {{ ref('fct_financeiro') }} as financeiro
inner join {{ ref('fct_embarque') }} as embarques on embarques.processo = financeiro.processo
where financeiro.categoria = 'DEMURRAGE'
    and (embarques.modal <> 'FCL' or embarques.direcao <> 'IMPORTACAO')
