-- 006: resultados de qualidade de dados (flowstream quality run).

create table if not exists ops.dq_results (
    id bigint generated always as identity primary key,
    run_id bigint not null references ops.pipeline_runs (id),
    executado_em timestamptz not null default now(),
    tipo text not null,                 -- test | model | seed | snapshot | freshness | dbt
    recurso text not null,              -- unique_id do dbt
    nome text not null,
    status text not null,               -- pass, fail, warn, error, success, skipped...
    linhas_com_falha integer,
    duracao_s numeric(10, 3) not null,
    mensagem text                       -- mascarada (sem CNPJ, CPF, e-mail), até 500 caracteres
);

create index if not exists dq_results_run_idx on ops.dq_results (run_id);
create index if not exists dq_results_executado_idx on ops.dq_results (executado_em);

create table if not exists ops.dq_anomalias (
    id bigint generated always as identity primary key,
    run_id bigint not null references ops.pipeline_runs (id),
    detectado_em timestamptz not null default now(),
    tabela text not null,
    data_referencia date not null,
    linhas_no_dia integer not null,
    media_14_dias numeric(14, 2) not null,
    desvio_pct numeric(9, 4) not null,  -- fração: 0,80 = 80% acima da média
    direcao text not null,
    constraint dq_anomalias_direcao_check check (direcao in ('ACIMA', 'ABAIXO'))
);

create index if not exists dq_anomalias_run_idx on ops.dq_anomalias (run_id);

comment on table ops.dq_results is 'Um resultado por teste, modelo, seed, snapshot e fonte em cada flowstream quality run.';
comment on table ops.dq_anomalias is 'Cargas do dia que desviam mais de 50% da média dos 14 dias anteriores.';
