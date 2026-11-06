# Fixtures

Respostas **reais** das APIs públicas, capturadas uma vez e usadas pelos testes unitários
(que nunca acessam a rede). Não contêm dados pessoais.

| Pasta | Origem | Observação |
| --- | --- | --- |
| `ptax/` | API Olinda do BCB, `CotacaoMoedaPeriodo`, boletim de fechamento | USD e EUR de 02 a 10/01/2025; um fim de semana (lista vazia) |
| `comexstat/` | `POST /general` do Comex Stat, SC, vias marítima e aérea, país China, set/2026 | `data.list` truncada nas primeiras 60 linhas para manter o repositório leve; `dates_updated.json` de `GET /general/dates/updated` |
| `dbt/` | `dbt/target/run_results.json` e `sources.json` reais deste projeto | `run_results_sucesso.json` e `sources.json` reduzidos a poucos resultados; `run_results_falha.json`, `run_results_erro_compilacao.json` e `sources_atrasada.json` derivados deles, mudando só status, falhas e mensagem |
| `documentos/` | Gerados pelo projeto (P09, P10), não são captura de API | `exemplo.pdf`: PDF mínimo para o teste manual da inbox. Os demais vêm de `generate.py` (reportlab, dados fictícios com dígitos verificadores válidos): BL, packing list e invoice do processo FS-2026-00123, um AWB, um BL escaneado (só imagem, para o OCR) e uma invoice com tentativa de prompt injection. O gabarito fica em `EXPECTED` no mesmo arquivo. Para regenerar: `.venv/Scripts/python tests/fixtures/documentos/generate.py` |
