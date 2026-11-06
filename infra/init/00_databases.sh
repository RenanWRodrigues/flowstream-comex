#!/bin/sh
# Executado pelo entrypoint do Postgres só na primeira subida (volume vazio).
# Cria o usuário da aplicação e o banco do n8n, com permissões mínimas.
# É um .sh (e não .sql) porque precisa ler as senhas das variáveis de ambiente.
set -eu

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -v app_db="$POSTGRES_DB" \
    -v app_user="$APP_DB_USER" \
    -v app_password="$APP_DB_PASSWORD" \
    -v n8n_user="$N8N_DB_USER" \
    -v n8n_password="$N8N_DB_PASSWORD" <<'EOSQL'
-- Usuário da aplicação: conecta e cria schemas só no banco do projeto
create role :"app_user" login password :'app_password';
revoke all on database :"app_db" from public;
grant connect, create, temporary on database :"app_db" to :"app_user";

-- Banco do n8n, isolado e de propriedade do usuário do n8n
create role :"n8n_user" login password :'n8n_password';
create database n8n owner :"n8n_user";
revoke all on database n8n from public;
EOSQL
