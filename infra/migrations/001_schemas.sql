-- 001: schemas das camadas de dados.
-- Os schemas pertencem ao usuário da aplicação, que roda as migrações.

create schema if not exists bronze;
create schema if not exists prata;
create schema if not exists ouro;
create schema if not exists ops;

comment on schema bronze is 'Dados exatamente como chegaram das fontes, com loaded_at.';
comment on schema prata is 'Dados tipados, padronizados e deduplicados (dbt staging e intermediate).';
comment on schema ouro is 'Star schema e KPIs consumidos pelo Power BI e pelos alertas (dbt marts).';
comment on schema ops is 'Operação da plataforma: execuções, documentos, revisões e alertas.';
