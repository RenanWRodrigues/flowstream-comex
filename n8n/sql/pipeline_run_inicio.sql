-- Abre a execução de um fluxo do n8n em ops.pipeline_runs (status EM_ANDAMENTO).
-- Usada por: n8n/flows/documento_recebido.json (nó "Abrir execução").
-- $1 = nome do pipeline (ex.: n8n_documento_recebido)
insert into ops.pipeline_runs (pipeline, status, rows_in)
values (cast($1 as text), 'EM_ANDAMENTO', 1)
returning id, status;
