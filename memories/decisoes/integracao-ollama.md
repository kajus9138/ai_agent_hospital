---
title: Integração com o LLM do Ollama
type: note
permalink: decisoes/integracao-ollama
tags:
- decisao
- ollama
- llm
---

# Integração com o LLM do Ollama

Decisões tomadas na tarefa 3 (Ollama LLM Integration), em 2026-10-27.

## Contexto
O agente ReAct precisa de um chat model compatível com LangChain/LangGraph servido pelo Ollama local,
e de um jeito de verificar o Ollama antes de iniciar. O texto da task sugeria pydantic-settings.

## Observations
- [decisao] `agent/llm.py`: `get_llm(settings=None, **kwargs)` devolve `ChatOllama` com temperatura 0.1; `kwargs` sobrescrevem os padrões (mesmo padrão de `create_pool`) #llm
- [alternativa-descartada] pydantic-settings: o `config.py` com dataclass + python-dotenv da task 1 já cobre OLLAMA_MODEL/OLLAMA_BASE_URL; não vale outra dependência #config
- [decisao] `check_ollama_health()` só é True se o servidor responde E o modelo configurado já foi baixado; checar só o servidor passaria e a primeira chamada daria 404 #ollama
- [convencao] Nome de modelo sem tag equivale a `:latest` (regra do Ollama); `llama3.2` não casa com `llama3.2:1b` #ollama
- [decisao] Health check usa o cliente oficial `ollama.AsyncClient` (`list()` em `/api/tags`), aberto com `async with` (fecha o pool do httpx); `ollama` e `httpx` declarados como dependências diretas; `ConnectionError`, `ResponseError`, `httpx.HTTPError` e `ValueError` (resposta 200 que não é do Ollama) viram False #ollama
- [alternativa-descartada] `ChatOllama(validate_model_on_init=True)`: levanta exceção na construção em vez de devolver bool, não serve como health check #ollama
- [convencao] Em `registro:5000/modelo`, só a parte após a última `/` pode ter tag #ollama
- [convencao] Testes sem Ollama injetam `httpx.MockTransport` via `async_client_kwargs={"transport": ...}` (API pública), sem mockar internals do ChatOllama #testes
- [convencao] Marker `ollama` separado do `integration` (Postgres), para rodar cada grupo sozinho; pulado se o modelo não estiver baixado. Com outro modelo: `OLLAMA_MODEL=llama3.2:1b uv run pytest -m ollama` #testes

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[Setup do projeto Python]]
