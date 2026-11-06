-- Fecha a execução aberta por pipeline_run_inicio.sql com SUCESSO ou ERRO.
-- Usada por: n8n/flows/documento_recebido.json (nós "Fechar com sucesso" e "Fechar com erro").
-- $1 = id da execução | $2 = SUCESSO ou ERRO | $3 = mensagem curta (vazia em caso de sucesso;
-- nunca CNPJ, valores ou conteúdo de documento)
update ops.pipeline_runs
set finished_at = now(),
    status = cast($2 as text),
    rows_out = case when cast($2 as text) = 'SUCESSO' then 1 else 0 end,
    error = nullif(left(cast($3 as text), 500), '')
where id = cast($1 as bigint)
  and status = 'EM_ANDAMENTO'
returning id, status;
