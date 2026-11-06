# tests/eval — conjunto de avaliação do agente de IA (P11)

40 PDFs fictícios (`documentos/<id>.pdf`), cada um com o gabarito `documentos/<id>.json`.
Métricas, regras de contagem e histórico em [docs/ia_avaliacao.md](../../docs/ia_avaliacao.md).

```bash
.venv/Scripts/python tests/eval/generate.py   # regenera (sai idêntico: PDFs determinísticos)
make evaluate                                  # flowstream ai evaluate (precisa do Ollama)
```

O gabarito traz:

| Chave | Conteúdo |
| --- | --- |
| `tipo`, `layout` | Tipo do documento e layout (`en_chave_valor`, `en_tabela`, `pt_chave_valor`) |
| `escaneado` | Página só com imagem (passa pelo OCR) |
| `erro_proposital` | Descrição do erro plantado, ou `null` |
| `regra_esperada` | Regra do validador que precisa pegar o erro (`FORMATO`, `COERENCIA`) |
| `injecao` | Tentativa de prompt injection (visível ou oculta) |
| `decisao_esperada` | `APROVADO` para os limpos; `REVISAO` para erro plantado e injeção |
| `texto` | Texto visível do documento (base para medir alucinação) |
| `campos` | Valores esperados, na forma de `ExtractionResult.campos()` |
| `evidencias` | Trecho literal de cada valor (o que um extrator perfeito citaria) |

Não edite os arquivos de `documentos/` à mão: mude `generate.py` e gere de novo. O teste
`tests/unit/ai/test_eval_dataset.py` confere que o conjunto versionado é o que o gerador
produz e que um extrator perfeito acerta 100% com ele.
