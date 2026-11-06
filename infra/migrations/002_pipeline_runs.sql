-- 002: log de execuções dos pipelines (ingestão, dbt, qualidade, exportação).

create table if not exists ops.pipeline_runs (
    id bigint generated always as identity primary key,
    pipeline text not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null,
    rows_in integer,
    rows_out integer,
    error text,
    constraint pipeline_runs_status_check
        check (status in ('EM_ANDAMENTO', 'SUCESSO', 'ERRO')),
    constraint pipeline_runs_rows_check
        check (coalesce(rows_in, 0) >= 0 and coalesce(rows_out, 0) >= 0),
    constraint pipeline_runs_finished_check
        check (finished_at is null or finished_at >= started_at)
);

create index if not exists pipeline_runs_pipeline_started_idx
    on ops.pipeline_runs (pipeline, started_at desc);

comment on table ops.pipeline_runs is 'Uma linha por execução de pipeline; status EM_ANDAMENTO até terminar.';
comment on column ops.pipeline_runs.error is 'Mensagem de erro resumida, sem dados pessoais nem valores.';
