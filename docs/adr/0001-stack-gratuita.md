# 0001 — Stack gratuita e local

- **Status:** aceita
- **Data:** 2026-11-02

## Contexto

O FlowStream-Comex é um projeto de portfólio que simula a plataforma de dados de um agente
de cargas internacional. As restrições são:

- **Custo zero:** nenhuma assinatura, nuvem paga ou API de LLM cobrada por token.
- **8 GB de RAM:** tudo precisa rodar em um notebook comum, com folga para o sistema.
- **Portfólio:** as ferramentas devem ser as que aparecem em vagas de engenharia e análise
  de dados (SQL, dbt, APIs, automação, IA aplicada, Power BI), e o projeto deve poder ser
  clonado e executado por qualquer pessoa.

## Opções consideradas

### A. Stack local de código aberto
PostgreSQL 16, dbt-core, n8n e Ollama em Docker ou nativos; Python 3.11 com FastAPI e
Streamlit; Power BI Desktop para o relatório.

- **Prós:** custo zero e sem limite de uso; reprodutível com `git clone` e Docker; mostra
  domínio de cada peça, em vez de serviços gerenciados que escondem os detalhes; os dados
  nunca saem da máquina.
- **Contras:** a memória é o gargalo (Docker, Ollama e Power BI não cabem juntos); um LLM
  de 3B parâmetros é menos preciso que modelos comerciais, o que exige validação forte;
  sem alta disponibilidade.

### B. Nuvem com camadas gratuitas
BigQuery ou Snowflake em período de teste, orquestrador gerenciado e API de LLM comercial.

- **Prós:** sem limite de memória local; LLM mais preciso.
- **Contras:** períodos de teste expiram e quebram o projeto para quem clonar depois; risco
  de cobrança; credenciais necessárias para rodar; documentos enviados a terceiros.

### C. Airflow e Spark locais
Airflow para orquestração e Spark para transformação.

- **Prós:** ferramentas muito pedidas no mercado.
- **Contras:** o Airflow sozinho consome de 2 a 4 GB; o Spark é desproporcional para alguns
  milhares de linhas; inviável junto com o Ollama em 8 GB.

## Decisão

Opção **A**. O Postgres concentra as camadas bronze, prata e ouro; o dbt-core faz as
transformações e os testes de dados; o n8n faz alertas e agendamento, com bem menos memória
que o Airflow; e o Ollama com `qwen2.5:3b` roda o agente de IA localmente, compensando a
menor precisão com schema, validadores de domínio, grounding e revisão humana. O Power BI
Desktop é gratuito, mas não é software livre e só roda no Windows; ele é o único item
proprietário, escolhido por ser o padrão de BI das empresas do setor.

## Consequências

- **Mais fácil:** qualquer pessoa reproduz o projeto sem conta paga; os testes rodam sem
  rede; a privacidade dos documentos é garantida por construção.
- **Mais difícil:** é preciso gerir memória (cada fase lista os serviços ligados, e todo
  container tem `mem_limit`); a acurácia do LLM precisa ser medida e controlada (P11).
- **Como reverter:** o acesso ao LLM fica atrás da interface `LLMClient`, e o acesso ao
  banco é SQL padrão e dbt; trocar o Ollama por uma API comercial, ou o Postgres por um
  data warehouse, afeta só os adapters e o profile do dbt.
