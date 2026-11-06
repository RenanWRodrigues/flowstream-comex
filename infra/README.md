# infra/

Infraestrutura local em Docker, dimensionada para 8 GB de RAM.

| Caminho | Conteúdo |
| --- | --- |
| `docker-compose.yml` | PostgreSQL 16 e n8n, com `mem_limit 512m` cada e portas só em 127.0.0.1 |
| `init/00_databases.sh` | Roda na primeira subida do Postgres: cria o usuário da aplicação e o banco do n8n |
| `migrations/NNN_nome.sql` | Migrações versionadas, aplicadas por `flowstream db migrate` |

- Senhas e usuários vêm do `.env` (o Makefile passa `--env-file .env`); nada fica no compose.
- O script de init é `.sh` (e não `.sql`) porque precisa ler as senhas das variáveis de ambiente.
- O Ollama roda fora do Docker.

Como operar: [docs/runbook.md](../docs/runbook.md). Por que SQL puro em vez de Alembic:
[ADR 0002](../docs/adr/0002-migracoes-sql-puro.md).
