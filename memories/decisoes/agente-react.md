---
title: Agente ReAct com LangGraph
type: note
permalink: decisoes/agente-react
tags:
- decisao
- langgraph
- agente
---

# Agente ReAct com LangGraph

Decisões tomadas na tarefa 6 (ReAct Agent with LangGraph), em 2026-10-27.

## Contexto
A task pedia `langgraph.prebuilt.create_react_agent` com `state_modifier` (ou `prompt`), checkpointer
Postgres, streaming e as tools do MCP de dengue. Verificado no Context7 e no código instalado
(langgraph 1.2.18, langchain 1.4.7).

## Observations
- [decisao] `agent/react_agent.py`: `HospitalReActAgent` usa `langchain.agents.create_agent(model, tools, system_prompt=..., checkpointer=...)`; dependência `langchain` adicionada #langgraph
- [alternativa-descartada] `create_react_agent`: deprecated desde o LangGraph 1.0 (`LangGraphDeprecatedSinceV10`); `state_modifier` nem existe mais (virou `prompt`, e no create_agent `system_prompt`) #langgraph
- [decisao] `create_hospital_agent(llm, mcp_client, checkpointer)` pega as tools de `load_langchain_tools`; nenhum nome de tool no código do agente, nem descrição de tool no prompt #mcp
- [decisao] `agent/checkpointer.py`: `open_checkpointer(conninfo=None)` cria um `AsyncConnectionPool` próprio (`autocommit`, `dict_row`, `prepare_threshold=0`), abre com `wait=True` e roda `setup()`; só a abertura vira `CheckpointerError` (qualquer `psycopg.Error`, inclusive `PoolTimeout`) #postgres
- [alternativa-descartada] `AsyncPostgresSaver.from_conn_string`: uma conexão única, sem reconexão; se o Postgres reinicia, o checkpointer morre até o processo reiniciar #postgres
- [alternativa-descartada] Passar o pool da task 2 ao saver: ele exige `autocommit=True` e `row_factory=dict_row`, e o `ThreadRepository` lê tuplas (`(thread_id,) = await cur.fetchone()`) #postgres
- [convencao] A task 7 (thread manager) reaproveita `open_checkpointer` em vez de criar outro `get_checkpointer` #postgres
- [decisao] `stream()` devolve o próprio gerador de `astream_events(version="v2")` (o v3 existe mas muda a forma dos eventos); sem camada extra, `aclose()` encerra o grafo na hora #langgraph
- [pendencia] Para a CLI (task 8): `GraphRecursionError` (modelo em loop de tools) e falha no meio de uma tool deixando `tool_calls` sem resposta no checkpoint da thread #agente
- [convencao] Testes unitários usam `ScriptedChatModel` (BaseChatModel com `_generate` só, `bind_tools` devolvendo self, guarda as mensagens recebidas) + `InMemorySaver`; sem `_stream`, o `astream_events` não perde os `tool_calls` #testes
- [convencao] `tests/test_agent_e2e.py` exige `ollama` e `dengue_mcp`; asserts de comportamento (tool chamada, admitir dado ausente), não de texto #testes
- [licao] Fixture async com `yield` não pode segurar o `DengueMCPClient`: o pytest-asyncio roda setup e teardown em tasks diferentes; abrir o cliente dentro do teste #testes
- [licao] `llama3.2:1b` chama tools com argumentos inventados e às vezes não termina em tempo útil; para validar o agente use `llama3.2` ou `qwen2.5` #ollama

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Cliente MCP do servidor de dengue]]
- depends_on [[Integração com o LLM do Ollama]]
- depends_on [[Persistência das threads no PostgreSQL]]
