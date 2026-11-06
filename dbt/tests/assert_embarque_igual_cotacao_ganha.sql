-- Regra: todo embarque nasce de uma cotação GANHA, com o mesmo cliente, modal e rota; e
-- toda cotação ganha tem exatamente um embarque.
select
    coalesce(embarques.cotacao_id, cotacoes.cotacao_id) as cotacao_id,
    embarques.processo,
    cotacoes.status
from {{ ref('fct_embarque') }} as embarques
full outer join (
    select cotacao_id, cliente_id, modal, rota_codigo, status
    from {{ ref('fct_cotacao') }}
    where ganha
) as cotacoes on cotacoes.cotacao_id = embarques.cotacao_id
where embarques.processo is null
    or cotacoes.cotacao_id is null
    or embarques.cliente_id <> cotacoes.cliente_id
    or embarques.modal <> cotacoes.modal
    or embarques.rota_codigo <> cotacoes.rota_codigo
