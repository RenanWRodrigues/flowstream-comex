# Runbook

Como operar a infraestrutura local do FlowStream-Comex. Todos os comandos rodam na raiz
do projeto, no Git Bash (Windows) ou num terminal Linux/macOS, com o `.venv` ativo.

## Pré-requisitos

1. Docker Desktop aberto (no Windows, com WSL2 limitado a 4 GB: veja abaixo).
2. Arquivo `.env` criado a partir do modelo:
   ```bash
   cp .env.example .env
   ```
   Troque as senhas e gere a `N8N_ENCRYPTION_KEY` com
   `python -c "import secrets; print(secrets.token_hex(32))"`. O usuário, a senha e a
   porta do `DATABASE_URL` precisam ser iguais a `APP_DB_USER`, `APP_DB_PASSWORD` e
   `POSTGRES_PORT`.

## Subir e parar

| Comando | O que faz |
| --- | --- |
| `make up` | Sobe só o Postgres e espera o healthcheck passar |
| `make up SERVICES="postgres n8n"` ou `make up-all` | Sobe Postgres e n8n |
| `make db-migrate` | Aplica as migrações pendentes (`infra/migrations/`) |
| `make down` | Para e remove os containers; **os dados ficam** nos volumes |
| `make psql` | Abre o `psql` no banco `flowstream` como usuário da aplicação |

O n8n abre em <http://localhost:5678>. Na primeira vez, ele pede para criar a conta do
proprietário (fica só no seu banco local).

Primeira subida completa:

```bash
make up-all && make db-migrate && make test-int
```

## Portas e usuários

| Serviço | Endereço no computador | Observação |
| --- | --- | --- |
| PostgreSQL 16 | `127.0.0.1:${POSTGRES_PORT}` (padrão do modelo: 5433) | Só aceita conexões locais |
| n8n | `127.0.0.1:5678` | Usa o banco `n8n` do mesmo Postgres |

| Usuário do banco | Para quê | Permissões |
| --- | --- | --- |
| `POSTGRES_USER` | Administração | Superusuário; a aplicação não usa |
| `APP_DB_USER` | Aplicação, migrações e dbt | Conecta e cria schemas só no banco `flowstream` |
| `N8N_DB_USER` | n8n | Dono do banco `n8n`; sem acesso ao `flowstream` |

Os usuários são criados por `infra/init/00_databases.sh` **só na primeira subida** (volume
vazio). Mudou as senhas no `.env` depois disso? Rode `make db-reset` ou altere com
`alter role ... password ...` no psql como administrador.

## dbt

`make dbt-seed` carrega os dados de referência e `make dbt` roda o `dbt build` completo
(também chamado pelo `make ci`). Os dois precisam do Postgres de pé. O Makefile lê
`APP_DB_USER`, `APP_DB_PASSWORD`, `POSTGRES_PORT` e `POSTGRES_DB` do `.env`; por isso, essas
senhas não podem conter `$` nem `#`.

Para rodar o dbt fora do make, exporte essas variáveis e use
`dbt <comando> --project-dir dbt --profiles-dir dbt`.

## Ver o consumo de memória

```bash
docker stats --no-stream
```

Postgres e n8n têm `mem_limit` de 512 MB cada. Valores típicos em repouso: Postgres de 30
a 80 MB e n8n de 150 a 250 MB. Se algum encostar no limite, veja `docker compose logs`.

## Migrações

- Ficam em `infra/migrations/NNN_nome.sql` e são aplicadas em ordem por
  `flowstream db migrate`, que registra cada uma em `ops.schema_migrations`.
- Rodar de novo não faz nada se não houver migração nova.
- **Nunca edite uma migração já aplicada.** O runner compara o checksum e recusa; crie uma
  nova migração com o próximo número. Decisão registrada no
  [ADR 0002](adr/0002-migracoes-sql-puro.md).
- Objetos dos schemas `prata` e `ouro` pertencem ao dbt e não entram em migrações.

## Resetar o banco

```bash
make db-reset
```

Pede confirmação (digite `sim`), apaga os volumes do Postgres **e do n8n** (os fluxos
ficam no banco `n8n`; exporte-os antes para `n8n/flows/`), sobe o Postgres de novo e
aplica as migrações.

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop fechado | Abra o Docker Desktop e espere o ícone ficar verde |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` | Outro serviço na porta | Troque `POSTGRES_PORT` no `.env` (e no `DATABASE_URL`) |
| `password authentication failed for user "flowstream"` | `.env` mudou depois da primeira subida, ou `DATABASE_URL` diferente de `APP_DB_*` | Confira o `.env`; se necessário, `make db-reset` |
| `flowstream db migrate` diz que não conecta | Postgres parado ou porta errada | `make up` e confira `POSTGRES_PORT` x `DATABASE_URL` |
| Conexões levam 10 s ou mais; testes de integração "travados" | `localhost` no `DATABASE_URL`: no Windows ele tenta `::1` (IPv6) primeiro, e o Docker Desktop aceita a conexão nessa porta sem responder | Use `127.0.0.1` no `DATABASE_URL` (como no `.env.example`) |
| `the input device is not a TTY` no `make psql` | Git Bash (mintty) sem TTY real | Rode `winpty make psql`, ou use o Windows Terminal |
| n8n reinicia em loop | Banco `n8n` não existe (volume criado antes do script de init) | `make db-reset` |
| Computador lento ou Docker travado no Windows | WSL2 usando memória demais | Veja a seção abaixo |

### Docker travado no Windows

1. Limite a memória do WSL2 em `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=4GB
   ```
2. Feche o Docker Desktop e, no PowerShell, rode `wsl --shutdown`.
3. Abra o Docker Desktop de novo e rode `make up`.
4. Se continuar travado: Docker Desktop → *Troubleshoot* → *Restart*. Como último recurso,
   *Clean / Purge data* (apaga todos os volumes; depois, `make up && make db-migrate`).
