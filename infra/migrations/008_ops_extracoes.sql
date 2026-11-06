-- 008: resultado de cada extração do agente de IA (P10). Uma linha por tentativa de
-- extração de um documento; ops.documentos guarda o status e o resultado mais recente.

create table if not exists ops.extracoes (
    id bigint generated always as identity primary key,
    documento_id uuid not null references ops.documentos (id) on delete cascade,
    tipo_documento text,                       -- BL, AWB, INVOICE, PACKING_LIST (null se não classificou)
    decisao text not null,
    score numeric(4, 3),
    campos jsonb,                              -- valores validados por campo
    evidencias jsonb,                          -- trecho literal do documento por campo
    divergencias jsonb not null default '[]',  -- [{regra, campo, gravidade, mensagem}]
    prompt_versao text,
    modelo text,
    tentativas smallint not null default 0,    -- chamadas ao LLM (1 ou 2)
    duracao_ms integer not null,
    paginas_ocr smallint not null default 0,
    criado_em timestamptz not null default now(),
    constraint extracoes_decisao_check check (decisao in ('APROVADO', 'REVISAO', 'ERRO')),
    constraint extracoes_tipo_check
        check (tipo_documento is null or tipo_documento in ('BL', 'AWB', 'INVOICE', 'PACKING_LIST')),
    constraint extracoes_score_check check (score is null or score between 0 and 1),
    constraint extracoes_aprovado_check
        check (decisao <> 'APROVADO' or (score >= 0.90 and tipo_documento is not null)),
    constraint extracoes_duracao_check check (duracao_ms >= 0),
    constraint extracoes_tentativas_check check (tentativas between 0 and 2)
);

create index if not exists extracoes_documento_idx on ops.extracoes (documento_id, criado_em desc);
create index if not exists extracoes_revisao_idx on ops.extracoes (decisao, criado_em)
    where decisao = 'REVISAO';

comment on table ops.extracoes is
    'Extração do agente de IA: campos, evidências, divergências, score e decisão. APROVADO exige score >= 0,90.';
comment on column ops.extracoes.divergencias is
    'Falhas dos validadores (formato, coerência, grounding, cruzamento); nunca contém texto do documento além das evidências.';
