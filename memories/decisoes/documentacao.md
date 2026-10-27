---
title: Documentação e guia de implantação
type: note
permalink: decisoes/documentacao
tags:
- decisao
- documentacao
- demo
---

# Documentação e guia de implantação

Decisões tomadas na tarefa 10 (Documentation and Deployment Guide), em 2026-10-27.

## Contexto
Última task do backlog. O PRD pede "documentação informativa e organizada". O README já servia de
referência de API, mas faltavam visão geral, quick start, tabela de configuração, arquitetura, guia do
MCP externo e roteiro de demo.

## Observations
- [decisao] Estrutura: README (quem roda: visão geral, quick start, configuração, exemplos, API), `docs/architecture.md` (quem mantém), `docs/mcp-integration.md` (quem configura o MCP), `DEMO.md` (quem apresenta), `docs/acceptance-criteria.md` (critérios do PRD com evidência) #documentacao
- [decisao] Diagramas em Mermaid (renderizam no GitHub e ficam versionados como texto) #documentacao
- [decisao] Comandos reais em vez dos do texto da task: `uv run ai-agent-hospital` (não `hospital-agent`), `docker compose` v2, `.env` em vez de `export` #documentacao
- [decisao] Critérios de aceite em arquivo separado; o `prd.txt` fica intocado como entrada do Task Master #taskmaster
- [decisao] `tests/test_docs.py` (offline): toda variável lida em `config.get_settings` precisa estar na tabela do README (as do MCP também no guia do MCP); links internos e âncoras (slug do GitHub) precisam resolver #testes
- [alternativa-descartada] Executar os snippets Python das docs em teste: exigiriam Ollama/PostgreSQL/MCP; os comportamentos já são cobertos pelos testes de integração #testes
- [decisao] DEMO.md com transcrições **reais** (qwen2.5, snapshot SE 40/2026), não respostas idealizadas; cada conversa diz o que destacar #demo
- [licao] qwen2.5 passa `semana=52` ao `comparativo_sazonal` quando perguntado sobre "a semana mais recente" sem contexto (deveria omitir o parâmetro) e lê o mínimo histórico como valor atual. Com a semana explícita ou depois de `situacao_atual` na mesma thread, acerta. Candidato a ajuste de prompt numa task futura #llm
- [licao] qwen2.5 às vezes encerra o turno anunciando "vamos consultar X" sem chamar a tool; uma pergunta de seguimento retoma #llm
- [licao] Bom momento de demo: com `serie_historica(inicio='20260701')` a tool devolve `isError`, e o agente corrige sozinho para SE (`202628`) — o ciclo ReAct visível #demo
- [convencao] Docstrings: português, curtas, explicando o porquê; `Args:`/`Raises:` só quando não é óbvio #documentacao

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Integração ponta a ponta e tratamento de erros]]
- depends_on [[Cliente MCP do servidor de dengue]]
