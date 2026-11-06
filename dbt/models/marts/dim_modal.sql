-- Grão: 1 linha por modal (lista fixa, igual a flowstream.domain.shipment.Modal).
with modais (modal, modal_nome, categoria, usa_conteiner, ordem) as (
    values
        ('FCL', 'Marítimo FCL (contêiner completo)', 'MARITIMO', true, 1),
        ('LCL', 'Marítimo LCL (carga consolidada)', 'MARITIMO', false, 2),
        ('AEREO', 'Aéreo', 'AEREO', false, 3),
        ('RODOVIARIO', 'Rodoviário', 'RODOVIARIO', false, 4),
        ('ISOTANQUE', 'Isotanque', 'MARITIMO', true, 5),
        ('PROJETO', 'Carga de projeto', 'MARITIMO', false, 6)
)

select
    modal::text as modal,
    modal_nome::text as modal_nome,
    categoria::text as categoria,
    usa_conteiner,
    ordem::integer as ordem
from modais
