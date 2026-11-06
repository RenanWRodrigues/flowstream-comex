---
name: finish-task
description: Encerra uma etapa do FlowStream-Comex com verificação, documentação e commit.
disable-model-invocation: true
---

# Concluir etapa

1. Rode make ci. Se falhar, corrija e rode de novo até passar.
2. Rode git diff --stat e git diff; procure: código morto, print, TODO esquecido,
   segredo, caminho absoluto, dado real, teste pulado sem motivo.
3. Confirme que docs/ e o README refletem o que mudou.
4. Adicione a entrada no CHANGELOG.md (seção Unreleased, formato Keep a Changelog).
5. Mostre a mensagem de commit proposta (Conventional Commits, em português) e
   espere aprovação.
6. Faça o commit. Não faça push.
