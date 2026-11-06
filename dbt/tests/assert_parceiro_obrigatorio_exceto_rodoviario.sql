-- Regra: todo embarque marítimo tem armador e todo aéreo tem companhia aérea; só o
-- rodoviário fica sem parceiro (as transportadoras ainda não são cadastradas).
select processo, modal, parceiro_id
from {{ ref('fct_embarque') }}
where (modal <> 'RODOVIARIO' and parceiro_id is null)
    or (modal = 'RODOVIARIO' and parceiro_id is not null)
