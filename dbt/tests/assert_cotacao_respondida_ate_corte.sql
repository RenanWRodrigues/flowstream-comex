-- Regra: toda cotação é respondida depois de pedida e nunca depois da data de corte.
select cotacao_id, solicitada_em, respondida_em
from {{ ref('fct_cotacao') }}
where respondida_em <= solicitada_em
    or (respondida_em at time zone 'America/Sao_Paulo')::date > {{ data_de_corte() }}
