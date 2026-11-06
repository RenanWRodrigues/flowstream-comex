# 0002 — Migrações em SQL puro, sem Alembic

- **Status:** aceita
- **Data:** 2026-11-02

## Contexto

O banco tem quatro schemas (`bronze`, `prata`, `ouro`, `ops`), mas a maior parte das
tabelas não é criada pela aplicação:

- `prata` e `ouro` são **inteiramente** do dbt, que cria e recria os modelos a cada build.
- `bronze` e `ops` recebem tabelas de carga e de operação (log de execuções, documentos,
  revisões, alertas), escritas pela aplicação Python.

Só esse segundo grupo precisa de migrações versionadas. As restrições do projeto são custo
zero, 8 GB de RAM e código fácil de ler para quem avalia o portfólio, e também valem as
regras do `CLAUDE.md` (dependência nova só com justificativa).

## Opções consideradas

### A. Alembic
- **Prós:** padrão de mercado com SQLAlchemy; gera migrações a partir de modelos ORM;
  suporta downgrade e branches.
- **Contras:** o projeto não usa modelos ORM (as tabelas de `bronze` e `ops` são simples e o
  resto é dbt), então o autogenerate não traria ganho; acrescenta `alembic.ini`, `env.py` e
  scripts Python que escondem o SQL de quem lê; o downgrade raramente é confiável em DDL
  real; mais uma dependência.

### B. Arquivos SQL numerados com um runner próprio (escolhida)
`infra/migrations/NNN_nome.sql`, aplicados em ordem por `flowstream db migrate` e
registrados em `ops.schema_migrations` (versão, nome, checksum, data).

- **Prós:** o SQL fica visível e revisável como está; o runner tem cerca de 60 linhas e
  é totalmente testado com um registro falso; o checksum impede alterar uma migração já
  aplicada; nenhuma dependência nova.
- **Contras:** sem downgrade automático; sem autogenerate; é preciso manter o runner (casos
  como `create index concurrently`, que não roda em transação, exigiriam ajuste).

### C. Ferramenta dedicada de migrações SQL (Flyway, dbmate, sqitch)
- **Prós:** mesmo modelo da opção B, já pronto e maduro.
- **Contras:** binário ou container extra (Flyway é Java e consome bem mais memória); mais
  uma peça para instalar e explicar, para um problema pequeno.

## Decisão

Opção **B**. Com o dbt cuidando das camadas analíticas, as migrações cobrem poucas tabelas
operacionais, e um runner pequeno, testado e legível atende melhor que uma ferramenta
genérica. Cada migração roda em uma transação junto com o seu registro: ou aplica inteira,
ou não deixa rastro.

## Consequências

- **Mais fácil:** revisar mudanças de banco (é SQL puro no diff); rodar em CI e nos testes
  de integração (`flowstream db migrate` é idempotente); entender o projeto sem conhecer
  Alembic.
- **Mais difícil:** desfazer uma migração exige escrever outra (`NNN_reverte_x.sql`); não
  há detecção automática de diferenças entre código e banco.
- **Regras:** nunca editar uma migração já aplicada (o runner recusa por checksum); nunca
  criar em migração objetos de `prata` ou `ouro`, que pertencem ao dbt.
- **Como reverter:** o Alembic pode ser adotado depois. Basta criar uma revisão base vazia,
  marcar o banco atual com `alembic stamp head` e passar a escrever novas migrações nele;
  `ops.schema_migrations` fica como histórico.
