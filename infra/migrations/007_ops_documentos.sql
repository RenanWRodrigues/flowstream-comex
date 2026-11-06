-- 007: documentos de embarque recebidos pela inbox (POST /v1/documentos).

create table if not exists ops.documentos (
    id uuid primary key default gen_random_uuid(),   -- não sequencial: não dá para "adivinhar" ids
    nome_arquivo text not null,
    sha256 char(64) not null,
    tamanho_bytes bigint not null,
    status text not null default 'RECEBIDO',
    tipo_documento text,                              -- BL, AWB, INVOICE, PACKING_LIST (P10)
    resultado jsonb,                                  -- extração validada (P10)
    erro text,
    recebido_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint documentos_sha256_unique unique (sha256),
    constraint documentos_tamanho_check check (tamanho_bytes > 0),
    constraint documentos_status_check
        check (status in ('RECEBIDO', 'PROCESSANDO', 'APROVADO', 'REVISAO', 'ERRO'))
);

create index if not exists documentos_status_idx on ops.documentos (status, recebido_em);

comment on table ops.documentos is
    'Um PDF da inbox por linha; o SHA-256 impede registrar o mesmo conteúdo duas vezes.';
