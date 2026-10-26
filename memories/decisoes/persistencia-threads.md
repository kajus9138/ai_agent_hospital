---
title: Persistência das threads no PostgreSQL
type: note
permalink: decisoes/persistencia-threads
tags:
- decisao
- postgres
- persistencia
---

# Persistência das threads no PostgreSQL

Decisões tomadas na tarefa 2 (PostgreSQL Database Schema and Connection), em 2026-10-26.

## Contexto
A task 2 pede tabelas próprias `threads` e `messages` com um repository; a task 7 usa o checkpointer do
LangGraph (`AsyncPostgresSaver`), que também guarda o estado/mensagens do grafo.

## Observations
- [decisao] Manter tabelas próprias `threads` + `messages` além do checkpointer: o checkpointer guarda o estado do grafo, `messages` é o histórico legível e consultável (preview, contagem, CLI). Duplicação aceita por simplicidade #postgres
- [alternativa-descartada] Só um catálogo `threads` e ler mensagens do checkpointer via `graph.aget_state`: sem duplicação, mas exigiria refazer as tasks 7/8 #postgres
- [decisao] Driver psycopg 3 + `psycopg_pool.AsyncConnectionPool`, sempre criado com `open=False` (abrir no construtor de pool async gera warning e vai virar erro) #psycopg
- [decisao] Credenciais do `docker-compose.yml` iguais ao `DATABASE_URL` padrão (`postgres/postgres`, banco `ai_agent_hospital`), e não `agent/agent_pwd` do texto da task #config
- [convencao] Schema em `db/schema.sql`, idempotente (`IF NOT EXISTS`), aplicado por `init_schema(pool)`; sem ferramenta de migração por ora #schema
- [licao] Ordem do histórico por `messages.seq` (identity), não por timestamp: `NOW()` é fixo na transação e `clock_timestamp()` pode empatar no microssegundo; UUID aleatório não serve de desempate #postgres
- [decisao] `role` aceita system/user/assistant/tool (espelha os tipos de mensagem do LangChain) #schema
- [convencao] Testes de integração (`@pytest.mark.integration`) rodam num schema temporário por teste (`search_path`) e são pulados sem Postgres; `TEST_DATABASE_URL` tem precedência sobre `DATABASE_URL` #testes

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Setup do projeto Python]]
