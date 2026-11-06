-- Grão: 1 linha por processo de embarque.
with embarques as (
    select
        processo, cotacao_id, cliente_id, modal, direcao, rota_codigo, origem, destino,
        armador_codigo, cia_aerea_prefixo, status, booking_em, etd, eta, atd, ata,
        quantidade_equipamentos, teus, peso_kg, volume_m3, peso_taxavel_kg
    from {{ ref('stg_embarques') }}
),

cotacoes as (
    select cotacao_id, vendedor_id
    from {{ ref('stg_cotacoes') }}
),

clientes as (
    select cliente_sk, cliente_id, valido_de, valido_ate
    from {{ ref('dim_cliente') }}
),

prazos as (
    select
        processo, transit_previsto_dias, transit_real_dias, atraso_saida_dias,
        atraso_chegada_dias, chegou_no_prazo, dias_uteis_booking_etd
    from {{ ref('int_embarque_timeline') }}
),

financeiro as (
    select
        processo,
        sum(valor_brl) filter (where tipo = 'RECEITA') as receita_brl,
        sum(valor_brl) filter (where tipo = 'CUSTO') as custo_brl,
        sum(valor_brl_assinado) as margem_brl
    from {{ ref('int_financeiro_brl') }}
    group by processo
),

final as (
    select
        embarques.processo,
        embarques.cotacao_id,
        clientes.cliente_sk,
        embarques.cliente_id,
        cotacoes.vendedor_id,
        embarques.rota_codigo,
        embarques.modal,
        embarques.direcao,
        coalesce(embarques.armador_codigo, embarques.cia_aerea_prefixo) as parceiro_id,
        embarques.armador_codigo,
        embarques.cia_aerea_prefixo,
        embarques.origem,
        embarques.destino,
        embarques.status,
        (embarques.booking_em at time zone 'America/Sao_Paulo')::date as data_booking,
        (embarques.etd at time zone 'America/Sao_Paulo')::date as data_etd,
        (embarques.eta at time zone 'America/Sao_Paulo')::date as data_eta,
        (embarques.atd at time zone 'America/Sao_Paulo')::date as data_atd,
        (embarques.ata at time zone 'America/Sao_Paulo')::date as data_ata,
        embarques.booking_em,
        embarques.etd,
        embarques.eta,
        embarques.atd,
        embarques.ata,
        embarques.quantidade_equipamentos,
        embarques.teus,
        embarques.peso_kg::numeric(14, 2) as peso_kg,
        embarques.volume_m3::numeric(12, 2) as volume_m3,
        embarques.peso_taxavel_kg::numeric(14, 2) as peso_taxavel_kg,
        prazos.transit_previsto_dias::numeric(8, 2) as transit_previsto_dias,
        prazos.transit_real_dias::numeric(8, 2) as transit_real_dias,
        prazos.atraso_saida_dias::numeric(8, 2) as atraso_saida_dias,
        prazos.atraso_chegada_dias::numeric(8, 2) as atraso_chegada_dias,
        prazos.chegou_no_prazo,
        prazos.dias_uteis_booking_etd,
        coalesce(financeiro.receita_brl, 0)::numeric(16, 2) as receita_brl,
        coalesce(financeiro.custo_brl, 0)::numeric(16, 2) as custo_brl,
        coalesce(financeiro.margem_brl, 0)::numeric(16, 2) as margem_brl
    from embarques
    left join cotacoes on cotacoes.cotacao_id = embarques.cotacao_id
    left join clientes
        on clientes.cliente_id = embarques.cliente_id
        and embarques.booking_em >= clientes.valido_de
        and embarques.booking_em < coalesce(clientes.valido_ate, 'infinity'::timestamptz)
    left join prazos on prazos.processo = embarques.processo
    left join financeiro on financeiro.processo = embarques.processo
)

select
    processo, cotacao_id, cliente_sk, cliente_id, vendedor_id, rota_codigo, modal, direcao,
    parceiro_id, armador_codigo, cia_aerea_prefixo, origem, destino, status,
    data_booking, data_etd, data_eta, data_atd, data_ata, booking_em, etd, eta, atd, ata,
    quantidade_equipamentos, teus, peso_kg, volume_m3, peso_taxavel_kg,
    transit_previsto_dias, transit_real_dias, atraso_saida_dias, atraso_chegada_dias,
    chegou_no_prazo, dias_uteis_booking_etd, receita_brl, custo_brl, margem_brl
from final
