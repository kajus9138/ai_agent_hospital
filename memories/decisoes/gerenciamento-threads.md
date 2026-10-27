---
title: Gerenciamento de threads
type: note
permalink: decisoes/gerenciamento-threads
tags:
- decisao
- postgres
- langgraph
- threads
---

# Gerenciamento de threads

Decisões tomadas na tarefa 7 (Thread Management and Persistence), em 2026-10-27.

## Contexto
O checkpointer do LangGraph (task 6) e as tabelas `threads`/`messages` (task 2) não estavam ligados:
nada criava a thread no catálogo nem gravava o histórico legível. A task pedia um `get_checkpointer`,
métodos de preview/resumo/exclusão no repository e um `ThreadManager(checkpointer, repository)` com
create, history e fork.

## Observations
- [decisao] `agent/thread_manager.py`: `ThreadManager(agent, repository)` recebe o `HospitalReActAgent` (e usa `agent.graph.checkpointer`), não o checkpointer solto: fork e sync precisam de `aget_state`/`aupdate_state` do grafo. Sem checkpointer → `ValueError` #threads
- [decisao] O UUID da thread no repository é o `thread_id` do grafo (como str) #threads
- [decisao] `messages` espelha o estado do grafo na mesma ordem; `sync_messages(thread_id)` grava o que está no estado além de `count_messages`. `send_message` chama no `finally`; a CLI (task 8), que usa `stream()`, deve chamar ao fim de cada turno #threads
- [alternativa-descartada] Gravar mensagens a partir dos eventos do stream: acoplaria o histórico ao formato do `astream_events` e perderia o que o grafo gravou numa falha #threads
- [decisao] O sync é uma operação só no repository (`append_missing_messages`): `SELECT ... FOR UPDATE` na thread + contagem + insert numa transação; syncs concorrentes da mesma thread não duplicam a cauda; tabela com mais mensagens que o estado → `HistoryDivergedError`; thread inexistente → `ThreadNotFoundError` (achados do /code-review) #postgres
- [decisao] Falha do agente em `send_message`: sync best-effort (`suppress`) e re-raise do erro original; cancelamento não dispara sync. Mesma regra na limpeza do fork #threads
- [decisao] `delete_thread` apaga o catálogo antes dos checkpoints: falha no meio deixa só checkpoint órfão, nunca thread listada sem estado #postgres
- [alternativa-descartada] Guardar `tool_call_id` em `messages`: sem coluna no schema; a tabela é para exibição e o checkpointer guarda o estado completo #schema
- [decisao] Metadados (contagem, primeira/última data, preview) derivados de `messages` por SQL (`LEFT JOIN LATERAL` na última por `seq`); schema inalterado #postgres
- [alternativa-descartada] Colunas `message_count`/`updated_at` em `threads`: exigiriam migração e manter contador em sincronia #postgres
- [decisao] `fork_thread(id, from_message)`: thread nova com as N primeiras mensagens via `graph.aupdate_state(novo_cfg, {"messages": msgs[:N]}, as_node="model")` (estado fica `next=()`); metadata `forked_from`/`from_message`. O corte tem de cair numa resposta final do assistente (sem `tool_calls`), senão `ValueError` #langgraph
- [alternativa-descartada] Fork na mesma thread via `checkpoint_id` (time travel): a original deixaria de ser uma conversa linear para o catálogo/CLI #langgraph
- [decisao] `delete_thread`: `checkpointer.adelete_thread` + `DELETE` em `threads` (cascade em `messages`) #postgres
- [convencao] `get_checkpointer` da task não existe: reaproveita `open_checkpointer` (convenção da task 6) #postgres
- [convencao] Fixtures de Postgres em `tests/conftest.py`: `database_url`, `schema_url` (conninfo com `search_path` num schema temporário, serve ao pool do repository e ao do checkpointer) e `pool` #testes

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Persistência das threads no PostgreSQL]]
- depends_on [[Agente ReAct com LangGraph]]
