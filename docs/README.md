# docs/

Documentação do FlowStream-Comex, atualizada a cada etapa.

| Arquivo | Conteúdo |
| --- | --- |
| [arquitetura.md](arquitetura.md) | Visão geral e diagrama do fluxo completo |
| [glossario.md](glossario.md) | Termos de comércio exterior e regras dos identificadores |
| [fontes.md](fontes.md) | Fontes de dados: PTAX, Comex Stat e gerador sintético; armadilhas das APIs |
| [modelo_dados.md](modelo_dados.md) | Camada ouro: star schema, fatos, dimensões e KPIs (diagrama Mermaid) |
| [api.md](api.md) | API FastAPI: autenticação, rotas, erros e exemplos de curl |
| [agente_ia.md](agente_ia.md) | Agente de IA: fluxo, schemas, validadores, score e uso |
| [riscos_ia.md](riscos_ia.md) | Riscos do agente de IA (alucinação, injeção, OCR...) e mitigações |
| [n8n.md](n8n.md) | Fluxos do n8n: credenciais, importar/exportar, entrada de documentos e watcher |
| [qualidade_dados.md](qualidade_dados.md) | O que é testado, onde ver a saúde dos dados e o que fazer quando falha |
| [dados_sinteticos.md](dados_sinteticos.md) | O que o gerador sintético produz, garantias e distribuições |
| [runbook.md](runbook.md) | Como subir, parar, migrar e resetar a infraestrutura; problemas comuns |
| [diario.md](diario.md) | Diário de bordo: correções feitas no código gerado |
| [adr/](adr/README.md) | Registros de decisões de arquitetura |

Arquivos que entram nas próximas fases: `ia_avaliacao.md`, `alertas.md`.
