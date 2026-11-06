-- Grão: 1 linha por processo de embarque.
with origem as (
    select
        processo, cotacao_id, cliente_id, modal, direcao, rota_codigo, origem, destino,
        armador_codigo, cia_aerea_prefixo, awb, bl_numero, booking_em, etd, eta, atd, ata,
        status, quantidade_equipamentos, teus, peso_kg, volume_m3, peso_taxavel_kg
    from {{ source('bronze', 'embarques') }}
),

final as (
    select
        upper(trim(processo)) as processo,
        upper(trim(cotacao_id)) as cotacao_id,
        upper(trim(cliente_id)) as cliente_id,
        upper(trim(modal)) as modal,
        upper(trim(direcao)) as direcao,
        upper(trim(rota_codigo)) as rota_codigo,
        upper(replace(origem, ' ', '')) as origem,
        upper(replace(destino, ' ', '')) as destino,
        upper(trim(armador_codigo)) as armador_codigo,
        trim(cia_aerea_prefixo) as cia_aerea_prefixo,
        trim(awb) as awb,
        upper(trim(bl_numero)) as bl_numero,
        booking_em,
        etd,
        eta,
        atd,
        ata,
        upper(trim(status)) as status,
        quantidade_equipamentos,
        teus,
        peso_kg::numeric(12, 2) as peso_kg,
        volume_m3::numeric(10, 2) as volume_m3,
        peso_taxavel_kg::numeric(12, 2) as peso_taxavel_kg
    from origem
)

select
    processo, cotacao_id, cliente_id, modal, direcao, rota_codigo, origem, destino,
    armador_codigo, cia_aerea_prefixo, awb, bl_numero, booking_em, etd, eta, atd, ata,
    status, quantidade_equipamentos, teus, peso_kg, volume_m3, peso_taxavel_kg
from final
