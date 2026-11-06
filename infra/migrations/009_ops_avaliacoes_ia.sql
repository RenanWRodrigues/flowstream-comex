-- 009: histórico das avaliações do agente de IA contra o gabarito (P11).
-- Uma linha por execução de `flowstream ai evaluate`; comparar versões de prompt e de modelo
-- só faz sentido entre linhas com o mesmo conjunto_sha256.

create table if not exists ops.avaliacoes_ia (
    id bigint generated always as identity primary key,
    executado_em timestamptz not null,
    prompt_versao text not null,
    modelo text not null,
    conjunto_sha256 char(64) not null,          -- PDFs + gabaritos avaliados
    documentos integer not null,
    classificacao_correta numeric(5, 4) not null,
    acuracia_exata numeric(5, 4) not null,
    acuracia_normalizada numeric(5, 4) not null,
    acuracia_criticos numeric(5, 4) not null,  -- normalizada, só campos críticos
    acuracia_preenchidos numeric(5, 4) not null, -- normalizada, só campos com valor no gabarito
    taxa_alucinacao numeric(5, 4),              -- valores fora do gabarito e do texto; null se nada foi extraído
    recall_erros numeric(5, 4),                 -- pela regra esperada; null sem erro plantado
    injecoes integer not null,
    injecoes_aprovadas integer not null,
    aprovacoes_indevidas integer not null,      -- armadilhas (erro ou injeção) APROVADAS
    aprovados_com_critico_errado integer not null,
    taxa_aprovacao_automatica numeric(5, 4),    -- documentos limpos aprovados sem revisão
    erros_tecnicos integer not null,
    tempo_medio_ms integer not null,
    tempo_p95_ms integer not null,
    detalhes jsonb not null,                    -- por campo e por documento, sem valores
    criado_em timestamptz not null default now(),
    constraint avaliacoes_ia_documentos_check check (documentos > 0),
    constraint avaliacoes_ia_taxas_check check (
        classificacao_correta between 0 and 1
        and acuracia_exata between 0 and 1
        and acuracia_normalizada between 0 and 1
        and acuracia_criticos between 0 and 1
        and acuracia_preenchidos between 0 and 1
        and (taxa_alucinacao is null or taxa_alucinacao between 0 and 1)
        and (recall_erros is null or recall_erros between 0 and 1)
        and (taxa_aprovacao_automatica is null or taxa_aprovacao_automatica between 0 and 1)
    ),
    constraint avaliacoes_ia_contagens_check check (
        injecoes >= 0
        and injecoes_aprovadas between 0 and injecoes
        and aprovacoes_indevidas >= injecoes_aprovadas
        and aprovados_com_critico_errado >= 0
        and erros_tecnicos between 0 and documentos
    ),
    constraint avaliacoes_ia_tempo_check check (tempo_medio_ms >= 0 and tempo_p95_ms >= 0)
);

create index if not exists avaliacoes_ia_versao_idx
    on ops.avaliacoes_ia (prompt_versao, modelo, executado_em desc);

comment on table ops.avaliacoes_ia is
    'Avaliação do agente de IA contra o gabarito de tests/eval (flowstream ai evaluate).';
comment on column ops.avaliacoes_ia.detalhes is
    'Acurácia por campo e resultado por documento; nunca valores extraídos nem texto.';
