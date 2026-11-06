# n8n/

Fluxos de automação do n8n (alertas, entrada de documentos, pipeline diário).

| Pasta | Conteúdo |
| --- | --- |
| `flows/` | Fluxos exportados em JSON, **sem credenciais** |
| `sql/` | Consultas usadas pelos fluxos, cada uma com teste de integração |

Regras na skill `.claude/skills/n8n-flow`: lógica Python só pela API ou pela CLI,
credenciais só no gerenciador do n8n e mensagens sem CNPJ nem valores.
