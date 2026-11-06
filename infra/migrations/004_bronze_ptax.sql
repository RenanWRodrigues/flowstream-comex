-- 004: PTAX do Banco Central (boletim de fechamento), carregada por flowstream ingest ptax.

create table if not exists bronze.ptax (
    moeda text not null,
    data_cotacao date not null,
    cotacao_compra numeric(12, 6) not null,
    cotacao_venda numeric(12, 6) not null,
    paridade_compra numeric(12, 6) not null,
    paridade_venda numeric(12, 6) not null,
    data_hora_cotacao timestamptz not null,
    tipo_boletim text not null,
    loaded_at timestamptz not null default now(),
    primary key (moeda, data_cotacao)
);

comment on table bronze.ptax is
    'PTAX (R$ por unidade da moeda), boletim de fechamento; só dias úteis. Fonte: API Olinda do BCB.';
