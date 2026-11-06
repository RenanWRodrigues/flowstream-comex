# Diário de bordo

Registro do que foi corrigido ou ajustado no código gerado pelo Claude Code. Este arquivo
alimenta o `docs/como_foi_feito.md` e serve de material para entrevistas.

Formato de cada entrada:

```markdown
## AAAA-MM-DD — Pnn: título curto
- **O que foi gerado:** ...
- **O problema:** ...
- **A correção:** ...
- **Lição:** ...
```

<!-- Entradas abaixo, da mais recente para a mais antiga. -->

## 2026-11-05 — P11: métricas de avaliação davam falso acerto
- **O que foi gerado:** `same_value` comparava números pelo valor e, se diferissem, caía na
  comparação de texto sem pontuação; `found_in_text` procurava o valor como substring do
  texto inteiro sem espaços; o recall contava qualquer documento em REVISAO.
- **O problema:** o subagente `code-reviewer` mostrou que `340.5` e `34.05` (e `-5` e `5`)
  viravam "acerto", o que inflava a acurácia e escondia alucinação e crítico errado;
  `GRU` "aparecia" em `Agrupamento`; um erro plantado que ia para revisão por score baixo
  contava como detectado. Os testes passavam porque os casos fabricados não cobriam isso.
- **A correção:** números diferentes nunca são iguais; busca por token inteiro (ou tokens
  seguidos, para `LH 506` e CNPJ formatado); `regra_esperada` no gabarito e recall só com a
  divergência dessa regra; acurácia dos preenchidos; alucinação também com tipo errado;
  execução com ERRO não vai para o histórico. Cada caso virou teste antes da correção.
- **Lição:** métrica também é código não confiável. Teste a métrica com o erro que ela
  deveria pegar, não só com o acerto.

## 2026-11-05 — P11: timeout de 120 s inviabilizava a avaliação na CPU
- **O que foi gerado:** a primeira execução de `ai evaluate` usava o timeout de 120 s do
  `OllamaClient` (P10).
- **O problema:** na máquina de 8 GB, só CPU, um AWB levou 130 s; todos os documentos
  terminavam em ERRO por timeout, e a execução gravaria um histórico sem sentido.
- **A correção:** `--timeout` na avaliação (padrão 600 s), sem mudar a API; recusa de gravar
  execução com documento em ERRO.
- **Lição:** medir o tempo real antes de rodar 40 documentos; um único documento teria
  mostrado o problema em 2 minutos.
