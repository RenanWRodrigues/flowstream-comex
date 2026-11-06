# tests/

| Pasta | Conteúdo | Como rodar |
| --- | --- | --- |
| `unit/` | Testes rápidos, sem rede, banco ou Ollama (use respx, FakeLLM, `tmp_path`) | `make test` |
| `integration/` | Testes marcados com `@pytest.mark.integration`; precisam do Postgres | `make test-int` |
| `fixtures/` | Respostas gravadas de APIs e PDFs de exemplo (sem dados reais) | — |
| `eval/` | Documentos fictícios com gabarito para avaliar o agente de IA | `flowstream ai evaluate` |

`conftest.py` limpa as variáveis de ambiente do projeto antes de cada teste.
Cobertura mínima: 80% no total e 90% nos módulos de domínio.
