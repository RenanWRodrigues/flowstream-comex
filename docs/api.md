# API

API REST do FlowStream-Comex, consumida pelo n8n (P09, P13, P14) e pela tela de revisão (P12).

```bash
make api        # http://127.0.0.1:8000 ; Swagger em /docs ; OpenAPI em /openapi.json
```

- **Autenticação:** header `X-API-Key` com o valor de `API_KEY` do `.env` (gere com
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Só `/health` é pública. Sem
  `API_KEY` configurada, as rotas protegidas respondem 503.
- **Erros:** RFC 9457, `Content-Type: application/problem+json`, com `type`, `title`, `status`,
  `detail` e `instance`. Nunca há stack trace: erro inesperado devolve 500 com um código para
  procurar no log.
- **Escuta só em 127.0.0.1.** O n8n, no Docker, chama `http://host.docker.internal:8000`.

Nos exemplos, `API=http://127.0.0.1:8000` e `KEY` é a sua chave.

## GET /health

Banco e Ollama. 200 com `ok` (tudo de pé) ou `degradado` (sem Ollama: a API funciona, a extração
não); 503 sem o banco.

```bash
curl -s $API/health
# {"status":"degradado","banco":"ok","ollama":"indisponivel"}
```

## GET /v1/tracking/{container_number}

Linha do tempo do processo mais recente do contêiner. O número é validado pela ISO 6346 e
normalizado (aceita espaços e minúsculas).

```bash
curl -s -H "X-API-Key: $KEY" $API/v1/tracking/MSCU1234566
```

| Status | Quando |
| --- | --- |
| 200 | `container_numero`, `processo`, modal, rota, ETD/ETA/ATD/ATA e `eventos` em ordem |
| 401 | Sem chave ou chave errada |
| 404 | Número válido, mas sem processo |
| 422 | Número que não passa na ISO 6346 (ex.: dígito verificador errado) |

## GET /v1/embarques/risco?dias=3

Contêineres de importação chegados e não devolvidos com até `dias` dias livres restantes
(padrão 3; de 0 a 60), dos mais urgentes para os menos; inclui os já vencidos. Fonte:
`ouro.kpi_demurrage_risco`.

```bash
curl -s -H "X-API-Key: $KEY" "$API/v1/embarques/risco?dias=7"
# {"dias":7,"data_referencia":"2026-10-31","total":4,"conteineres":[{"processo":"IMP-...",
#   "container_numero":"...","dias_livres_restantes":4,"faixa_risco":"ATENCAO", ...}]}
```

## POST /v1/documentos

Registra um PDF **que já está em `data/inbox`** e o envia para extração (no P10; até lá, fica
em `RECEBIDO`). Responde **202** com o `id` e o header `Location`.

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"arquivo": "BL_MSCU1234566.pdf"}' $API/v1/documentos
# {"id":"4f0c…","status":"RECEBIDO"}
```

| Status | Quando |
| --- | --- |
| 202 | Registrado (`ops.documentos`) |
| 400 | Nome com caminho (`../../etc/passwd`, `/x`, `C:\x`, `sub/x.pdf`) ou que não é PDF |
| 404 | O arquivo não está na inbox |
| 409 | O mesmo conteúdo (SHA-256) já foi registrado; `documento_id` traz o id existente |
| 422 | Corpo inválido (sem `arquivo`, campo extra, tipo errado) |

**Segurança:** só um nome de arquivo é aceito (letras, dígitos, espaço, `. _ - ( )`), nunca um
caminho; depois, o caminho resolvido precisa estar dentro da inbox (defesa em profundidade
contra links simbólicos). A resposta de erro não repete o caminho recebido.

## GET /v1/documentos/{id}

```bash
curl -s -H "X-API-Key: $KEY" $API/v1/documentos/4f0c…
# {"id":"4f0c…","arquivo":"BL_MSCU1234566.pdf","status":"RECEBIDO","tipo_documento":null,
#  "resultado":null,"erro":null,"recebido_em":"…","atualizado_em":"…"}
```

404 se o documento não existe; 422 se o id não é um UUID. Os ids são UUID (não sequenciais),
para não dar para "adivinhar" documentos de outros clientes.

## Arquitetura

Rotas finas em `src/flowstream/api/routers/`: validam, autenticam e traduzem. A lógica fica nos
serviços (`flowstream.documents`, `flowstream.operations`), testados sem HTTP; os repositórios
Postgres ficam nos `adapters.py`. Os schemas de entrada e saída (`api/schemas.py`) são separados
dos modelos de domínio. Toda dependência (configuração, repositórios, processador, health) pode
ser trocada nos testes por `app.dependency_overrides`.
