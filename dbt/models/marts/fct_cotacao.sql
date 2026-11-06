-- Grão: 1 linha por cotação.
with cotacoes as (
    select
        cotacao_id, cliente_id, vendedor_id, modal, direcao, rota_codigo, solicitada_em,
        respondida_em, valor_frete, moeda, quantidade_equipamentos, peso_kg, volume_m3,
        status, motivo_perda
    from {{ ref('stg_cotacoes') }}
),

clientes as (
    select cliente_sk, cliente_id, valido_de, valido_ate
    from {{ ref('dim_cliente') }}
),

embarques as (
    select processo, cotacao_id
    from {{ ref('stg_embarques') }}
),

final as (
    select
        cotacoes.cotacao_id,
        clientes.cliente_sk,
        cotacoes.cliente_id,
        cotacoes.vendedor_id,
        cotacoes.rota_codigo,
        cotacoes.modal,
        cotacoes.direcao,
        (cotacoes.solicitada_em at time zone 'America/Sao_Paulo')::date as data_solicitacao,
        cotacoes.solicitada_em,
        cotacoes.respondida_em,
        round(
            (extract(epoch from cotacoes.respondida_em - cotacoes.solicitada_em) / 3600)::numeric,
            2
        )::numeric(10, 2) as tempo_resposta_horas,
        cotacoes.valor_frete::numeric(16, 2) as valor_frete,
        cotacoes.moeda,
        {{ to_brl(
            'cotacoes.valor_frete',
            'cotacoes.moeda',
            "(cotacoes.solicitada_em at time zone 'America/Sao_Paulo')::date"
        ) }}::numeric(16, 2) as valor_frete_brl,
        cotacoes.quantidade_equipamentos,
        cotacoes.peso_kg::numeric(14, 2) as peso_kg,
        cotacoes.volume_m3::numeric(12, 2) as volume_m3,
        cotacoes.status,
        cotacoes.status = 'GANHA' as ganha,
        cotacoes.motivo_perda,
        embarques.processo
    from cotacoes
    left join clientes
        on clientes.cliente_id = cotacoes.cliente_id
        and cotacoes.solicitada_em >= clientes.valido_de
        and cotacoes.solicitada_em < coalesce(clientes.valido_ate, 'infinity'::timestamptz)
    left join embarques on embarques.cotacao_id = cotacoes.cotacao_id
)

select
    cotacao_id, cliente_sk, cliente_id, vendedor_id, rota_codigo, modal, direcao,
    data_solicitacao, solicitada_em, respondida_em, tempo_resposta_horas, valor_frete, moeda,
    valor_frete_brl, quantidade_equipamentos, peso_kg, volume_m3, status, ganha,
    motivo_perda, processo
from final
