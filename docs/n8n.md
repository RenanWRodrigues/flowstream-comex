# Fluxos do n8n

Os fluxos ficam exportados em `n8n/flows/` (JSON **sem credenciais**) e as consultas SQL
que eles usam ficam em `n8n/sql/`, cada uma com teste de integração
(`tests/integration/test_n8n_sql.py`). As regras de construção estão na skill
`.claude/skills/n8n-flow`.

| Fluxo | Gatilho | O que faz |
| --- | --- | --- |
| [`documento_recebido`](#documento_recebido) | Webhook `POST /webhook/documento-recebido` | Registra na API o PDF que o watcher achou na inbox |

## Credenciais (uma vez por instalação)

As credenciais vivem só no gerenciador do n8n (**Overview → Credentials → Create**). Use
exatamente estes nomes: o JSON exportado procura a credencial pelo nome.

| Nome no n8n | Tipo | Preenchimento |
| --- | --- | --- |
| `FlowStream - Postgres (app)` | Postgres | Host `postgres`, porta `5432`, database = `POSTGRES_DB`, user = `APP_DB_USER`, password = `APP_DB_PASSWORD` (valores do `.env`), SSL `disable` |
| `FlowStream - token do webhook` | Header Auth | Name `X-Webhook-Token`, Value = `N8N_WEBHOOK_TOKEN` do `.env` |
| `FlowStream - chave da API` | Header Auth | Name `X-API-Key`, Value = `API_KEY` do `.env` |
| `FlowStream - bot do Telegram` | Telegram API | Token do bot (P13). Até lá o nó **Avisar no Telegram** fica desativado: o n8n não publica um fluxo com nó ativo sem credencial |

O host do Postgres é `postgres` (o nome do serviço no Docker Compose), não `127.0.0.1`: o
n8n roda dentro da rede do Docker.

## Importar um fluxo

1. No n8n: **Overview → Create workflow → ⋯ → Import from File** e escolha
   `n8n/flows/<nome>.json`.
2. Abra cada nó com credencial e confira se a credencial certa foi selecionada pelo nome.
3. **Publish** (canto superior direito) para ativar o webhook de produção.

## Exportar depois de mudar um fluxo

O JSON versionado não pode ter ids de credenciais nem dados de teste (`pinData`). Exporte
pela CLI do n8n e limpe com a CLI do projeto:

No Git Bash do Windows, `MSYS_NO_PATHCONV=1` impede que `/tmp` vire um caminho do Windows.

```bash
MSYS_NO_PATHCONV=1 docker exec flowstream-n8n n8n export:workflow --id=<ID> --output=/tmp/fluxo.json
MSYS_NO_PATHCONV=1 docker cp flowstream-n8n:/tmp/fluxo.json data/processed/fluxo.json
.venv/Scripts/flowstream n8n clean-export data/processed/fluxo.json n8n/flows/<nome>.json
```

`tests/unit/test_n8n_flows.py` falha se sobrar id de credencial, dado da instância, segredo
ou SQL diferente do de `n8n/sql/`.

---

## documento_recebido

Entrada automática de documentos (P09). Depende da API (`make api`) e do watcher
(`make watch`).

```text
PDF salvo em data/inbox
  -> watcher (make watch): espera o arquivo parar de crescer, calcula o SHA-256
  -> POST /webhook/documento-recebido  {arquivo, sha256, tamanho_bytes}  + X-Webhook-Token
  -> n8n: Abrir execução -> responde 202 ao watcher -> POST /v1/documentos -> 202? -> Fechar com sucesso
                                               \-> outro status ou API fora -> Fechar com erro
                                                   -> Marcar execução como falha -> Error Trigger
                                                   -> Telegram
```

**Gatilho:** webhook `POST http://127.0.0.1:5678/webhook/documento-recebido`, autenticado
pelo header `X-Webhook-Token`. Responde **202 só depois de abrir a execução** em
`ops.pipeline_runs` (nó *Responder ao watcher*): se o Postgres do n8n falhar antes disso, o
watcher recebe 5xx, tenta de novo e grava o ERRO do lado dele. O resultado do registro na
API fica em `ops.pipeline_runs` e na lista de execuções do n8n.

**Passos:**

| Nó | O que faz |
| --- | --- |
| Normalizar aviso | Pega `arquivo`, `sha256` e `tamanho_bytes` do corpo |
| Abrir execução | `n8n/sql/pipeline_run_inicio.sql`: linha `n8n_documento_recebido` em `EM_ANDAMENTO` |
| Responder ao watcher | 202 com `{"execucao": <id>}`; daqui em diante, falhas ficam só no n8n e no banco |
| Registrar documento na API | `POST http://host.docker.internal:8000/v1/documentos` com `X-API-Key` |
| API aceitou (202)? | 202 segue para sucesso; qualquer outro status (400, 404, 409, 5xx) segue para erro |
| Fechar com sucesso / com erro | `n8n/sql/pipeline_run_fim.sql`; o erro guarda só o status HTTP e o título do problema |
| Marcar execução como falha | Faz a execução terminar em erro, para disparar o Error Trigger do próprio fluxo (não precisa configurar *Error workflow*) |
| Falha no fluxo → Avisar no Telegram | Mensagem com nome do fluxo, nó, id da execução e horário (sem CNPJ, valores nem nome de arquivo). **Desativado até o P13** |

**Saídas:** uma linha em `ops.documentos` (status `RECEBIDO`) e uma em `ops.pipeline_runs`
(`n8n_documento_recebido`, `SUCESSO` ou `ERRO`).

**Quem faz o quê:**

- O **watcher** cuida de arquivo incompleto, temporário (`.crdownload`, `.part`, `~$`),
  não-PDF e duplicado (mesmo SHA-256 com outro nome vai para `data/processed/duplicados`).
  Se o webhook falhar 3 vezes (backoff de 1 s e 2 s; só em erro de rede, 429 ou 5xx), grava
  `inbox_watcher` com `ERRO` em `ops.pipeline_runs` e não insiste até ser reiniciado. Ao
  reiniciar, ele relê a inbox; PDFs que a API já aceitou (mesmo hash e mesmo nome) ficam
  onde estão.
- Um arquivo só está pronto quando **tamanho e data de modificação** ficam iguais em duas
  leituras (há cópias que pré-alocam o tamanho final). Cópias iguais que chegam juntas: a
  primeira é avisada e as outras vão para `duplicados`, sem esperar o n8n gravar no banco.
- Banco fora do ar: o arquivo espera 5 s, 10 s, 20 s... (até 1 min) antes de cada nova
  tentativa, com um aviso no log só na primeira falha. Qualquer erro inesperado num arquivo
  vira `ERRO` em `ops.pipeline_runs` e o watcher segue com os demais.
- O webhook é chamado sem proxy do sistema e sem seguir redirecionamentos (o token não sai
  do endereço configurado).
- O **n8n** registra e audita a execução.
- A **API** valida o nome (sem caminhos), recalcula o SHA-256 e recusa duplicados com 409.

### Watcher e memória

O P09 limita o watcher a 50 MB de RAM. Por isso ele não usa SQLAlchemy, httpx, Typer nem
tenacity (só esses imports já passavam de 58 MB): fala com o Postgres por `psycopg` direto e
com o webhook por `urllib`. `tests/unit/ingestion/test_inbox_watcher.py` falha se alguma
dessas bibliotecas voltar a ser importada.

| Como rodar | Memória medida (Windows, processo ativo) |
| --- | --- |
| `make watch` = `python -m flowstream.ingestion.inbox_watcher` | ~46 MB |
| `flowstream inbox watch` (carrega a CLI inteira) | ~75 MB |

Use o `make watch` no dia a dia; o comando da CLI existe por conveniência.
### Como testar

Sem n8n (unitário): `make test` cobre o watcher com relógio falso e webhook simulado
(`tests/unit/ingestion/test_inbox_watcher.py`) e a estrutura do JSON
(`tests/unit/test_n8n_flows.py`). Com Postgres: `make test-int` roda as consultas do fluxo (`test_n8n_sql.py`) e as do
watcher (`test_inbox_store.py`).

Ponta a ponta, com três terminais:

```bash
make up-all    # Postgres + n8n
make api       # terminal 2
make watch     # terminal 3
cp tests/fixtures/documentos/exemplo.pdf data/inbox/
```

Em seguida, no `make psql`:

```sql
select nome_arquivo, status, recebido_em from ops.documentos order by recebido_em desc limit 1;
select pipeline, status, error from ops.pipeline_runs
 where pipeline in ('n8n_documento_recebido', 'inbox_watcher') order by id desc limit 3;
```

### Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| Watcher: `HTTP 404` | Fluxo não publicado (o webhook de produção só existe depois do **Publish**) |
| Watcher: `HTTP 403` | `N8N_WEBHOOK_TOKEN` do `.env` diferente da credencial `FlowStream - token do webhook` |
| `ops.pipeline_runs`: `API inacessível` | `make api` parado, ou o container não alcança `host.docker.internal:8000` |
| `ops.pipeline_runs`: `HTTP 401` | Credencial `FlowStream - chave da API` diferente do `API_KEY` |
| `ops.pipeline_runs`: `HTTP 503` | A API subiu sem `API_KEY` (ela só lê o `.env` ao iniciar: reinicie o `make api`) |
| `ops.pipeline_runs`: `HTTP 404: Arquivo não encontrado na inbox.` | O PDF saiu da inbox antes de a API ler |
