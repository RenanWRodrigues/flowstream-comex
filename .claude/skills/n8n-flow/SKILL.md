---
name: n8n-flow
description: Use ao criar ou alterar fluxos do n8n no FlowStream-Comex (webhooks, alertas, agendamentos, orquestração).
---

# Fluxo n8n

1. Toda consulta SQL do fluxo fica em n8n/sql/<nome>.sql e tem teste pytest de
   integração com dados sintéticos controlados. O fluxo só referencia a consulta.
2. Toda chamada de lógica Python vai pela API FastAPI ou pela CLI, nunca por código
   Python colado dentro de um nó.
3. Credenciais só pelo gerenciador de credenciais do n8n; nada de token no JSON.
4. Todo fluxo tem: nó de erro (Error Trigger) que avisa no Telegram, e gravação
   em ops.pipeline_runs no início e no fim.
5. Mensagens não contêm CNPJ nem valores: só número do processo, rota e datas.
6. Exporte o fluxo para n8n/flows/<nome>.json (sem credenciais) e documente em
   docs/n8n.md: gatilho, passos, saídas, como testar.
