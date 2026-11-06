-- 003: tabelas do bronze para a operação sintética (P03).
-- Bronze guarda os dados como chegaram: sem chaves estrangeiras, só a chave natural e
-- loaded_at. As colunas seguem os CSVs de flowstream synthetic generate.

create table if not exists bronze.vendedores (
    vendedor_id text primary key,
    nome text not null,
    data_admissao date not null,
    loaded_at timestamptz not null default now()
);

create table if not exists bronze.clientes (
    cliente_id text primary key,
    cnpj text not null unique,
    razao_social text not null,
    segmento text not null,
    porte text not null,
    uf text not null,
    vendedor_id text not null,
    data_cadastro date not null,
    loaded_at timestamptz not null default now()
);

create table if not exists bronze.cotacoes (
    cotacao_id text primary key,
    cliente_id text not null,
    vendedor_id text not null,
    modal text not null,
    direcao text not null,
    rota_codigo text not null,
    origem text not null,
    destino text not null,
    solicitada_em timestamptz not null,
    respondida_em timestamptz not null,
    valor_frete numeric(14, 2) not null,
    moeda text not null,
    quantidade_equipamentos integer not null,
    peso_kg numeric(12, 2) not null,
    volume_m3 numeric(10, 2) not null,
    status text not null,
    motivo_perda text,
    loaded_at timestamptz not null default now()
);

create table if not exists bronze.embarques (
    processo text primary key,
    cotacao_id text not null,
    cliente_id text not null,
    modal text not null,
    direcao text not null,
    rota_codigo text not null,
    origem text not null,
    destino text not null,
    armador_codigo text,
    cia_aerea_prefixo text,
    awb text,
    bl_numero text,
    booking_em timestamptz not null,
    etd timestamptz not null,
    eta timestamptz not null,
    atd timestamptz,
    ata timestamptz,
    status text not null,
    quantidade_equipamentos integer not null,
    teus integer not null,
    peso_kg numeric(12, 2) not null,
    volume_m3 numeric(10, 2) not null,
    peso_taxavel_kg numeric(12, 2),
    loaded_at timestamptz not null default now()
);

create table if not exists bronze.equipamentos (
    processo text not null,
    numero text not null,
    tipo text not null,
    peso_kg numeric(12, 2) not null,
    free_time_dias integer not null,
    loaded_at timestamptz not null default now(),
    primary key (processo, numero)
);

create table if not exists bronze.itens_financeiros (
    item_id text primary key,
    processo text not null,
    tipo text not null,
    categoria text not null,
    valor numeric(14, 2) not null,
    moeda text not null,
    competencia date not null,
    loaded_at timestamptz not null default now()
);

create table if not exists bronze.tracking_eventos (
    evento_id text primary key,
    processo text not null,
    tipo text not null,
    ocorrido_em timestamptz not null,
    local text not null,
    eta_informada timestamptz,
    loaded_at timestamptz not null default now()
);

comment on table bronze.embarques is 'Embarques sintéticos (flowstream synthetic load): 1 linha por processo.';
comment on table bronze.itens_financeiros is 'Receitas e custos por processo, na moeda original e com data de competência.';
