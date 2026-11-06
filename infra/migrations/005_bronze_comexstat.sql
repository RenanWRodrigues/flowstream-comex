-- 005: Comex Stat (MDIC), exportação e importação de SC por mês, país, posição SH4 e via.

create table if not exists bronze.comexstat (
    fluxo text not null,                  -- EXPORTACAO | IMPORTACAO
    ano integer not null,
    mes integer not null,
    pais text not null,                   -- nome em português, como devolvido pela API
    sh4_codigo text not null,             -- posição do Sistema Harmonizado (4 dígitos)
    sh4 text not null,
    via text not null,                    -- MARITIMA | AEREA
    valor_fob_usd numeric(16, 2) not null,
    peso_kg numeric(16, 2) not null,
    frete_usd numeric(16, 2),             -- só na importação
    seguro_usd numeric(16, 2),            -- só na importação
    loaded_at timestamptz not null default now(),
    primary key (fluxo, ano, mes, pais, sh4_codigo, via),
    constraint comexstat_mes_check check (mes between 1 and 12)
);

comment on table bronze.comexstat is
    'Comércio exterior de SC (Comex Stat/MDIC), vias marítima e aérea; os 24 últimos meses publicados.';
