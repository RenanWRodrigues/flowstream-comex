# src/

Código-fonte do pacote `flowstream`, instalado em modo editável com `make install`.

| Caminho | Conteúdo |
| --- | --- |
| `flowstream/cli.py` | CLI `flowstream` (Typer): grupos `ingest`, `synthetic`, `ai`, `export` e `version` |
| `flowstream/config.py` | `Settings` — toda a configuração vem de variáveis de ambiente |
| `flowstream/logging.py` | Logging em JSON (arquivo) e texto (terminal), com CNPJ, CPF e e-mail mascarados |
| `flowstream/domain/` | Regras puras do comércio exterior — sem I/O |
| `flowstream/synthetic/` | Gerador de dados fictícios |
| `flowstream/ingestion/` | Fontes externas e watcher da inbox |
| `flowstream/api/` | API FastAPI |
| `flowstream/ai/` | Agente de extração e validação de documentos |
| `flowstream/review/` | Tela de revisão humana |
| `flowstream/alerts/` | Alertas operacionais |
| `flowstream/export/` | Exportação para o Power BI |

Cada módulo de negócio segue `domain.py` (regras puras) → `service.py` (orquestra) →
`adapters.py` (HTTP, banco, arquivos). Lógica pura nunca importa adapters.
