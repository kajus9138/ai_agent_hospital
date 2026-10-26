---
title: Setup do projeto Python
type: note
permalink: decisoes/setup-do-projeto-python
tags:
- decisao
- setup
- tooling
---

# Setup do projeto Python

Decisões tomadas na tarefa 1 (Project Setup and Dependencies), em 2026-10-26.

## Contexto
POC de agente ReAct (LangGraph + LLM local no Ollama), com threads no PostgreSQL e um MCP local via stdio.
A tarefa pedia Python 3.12, pyproject.toml, ruff/black e pytest.

## Observations
- [decisao] Gestor de pacotes: uv, layout `src/`, build backend hatchling, `uv.lock` versionado #uv
- [decisao] Python travado em `>=3.12,<3.13` (PRD exige 3.12) e `.python-version` = 3.12 #python
- [decisao] Só ruff para lint e formatação (`ruff format`); black descartado por ser redundante #ruff
- [decisao] Threads via `langgraph-checkpoint-postgres` + `psycopg[binary,pool]`, padrão da doc oficial do LangGraph; asyncpg descartado #postgres
- [decisao] Cliente MCP com `langchain-mcp-adapters` (converte tools MCP em tools LangChain), sobre o pacote `mcp` #mcp
- [convencao] Configuração em `config.py`: dataclass `Settings` + `get_settings()` com python-dotenv; variáveis OLLAMA_MODEL, OLLAMA_BASE_URL, DATABASE_URL #config
- [convencao] pre-commit roda `ruff check`, `ruff format --check` e `pytest` via `uv run` (mesma versão do lock) #pre-commit
- [licao] O task-master normaliza o `tasks.json` ao gravar (ids de dependência viram string, `parentId`); diffs grandes nesse arquivo após um `update-task` são esperados #taskmaster

## Relations
- part_of [[ai_agent_hospital]]
