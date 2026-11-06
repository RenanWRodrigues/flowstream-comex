# data/

Arquivos de dados locais. Só a estrutura de pastas vai para o Git.

| Pasta | Conteúdo | No Git? |
| --- | --- | --- |
| `inbox/` | PDFs de documentos aguardando processamento | não |
| `processed/` | Documentos já processados (e `duplicados/`) | não |
| `synthetic/` | CSVs gerados por `flowstream synthetic generate` (um por tabela do bronze), para inspeção | não |
| `powerbi/` | Parquet exportados para o Power BI | não |
| `private/` | Qualquer dado sensível — nunca lido nem escrito pelo Claude Code | não |

**Nunca** coloque dados reais de clientes neste repositório.
