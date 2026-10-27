---
title: Integração ponta a ponta e tratamento de erros
type: note
permalink: decisoes/integracao-erros
tags:
- decisao
- erros
- health
- retry
---

# Integração ponta a ponta e tratamento de erros

Decisões tomadas na tarefa 9 (End-to-End Integration and Error Handling), em 2026-10-27.

## Contexto
A task pedia um `create_agent()` em `main.py`, erros tipados por serviço, retry com backoff, um
"health endpoint" e shutdown gracioso. A montagem já existia em `cli.open_session` (task 8), o retry
do MCP no `DengueMCPClient.connect` (task 4) e o `AsyncExitStack` já fechava tudo.

## Observations
- [decisao] `errors.py`: base `AgentHospitalError` + `OllamaConnectionError`, `DatabaseConnectionError`, `MCPConnectionError` (movido para cá, ainda exportado por `mcp_client`), `ToolExecutionError(tool_name)`; `CheckpointerError` herda de `DatabaseConnectionError`. A CLI captura a base no `_run` (exit 1); `StartupError` saiu #erros
- [decisao] Montagem em `bootstrap.open_session` (saiu de `cli.py`); a CLI importa o nome, então os testes continuam fazendo `monkeypatch.setattr(cli, "open_session", ...)` #cli
- [alternativa-descartada] `create_agent()` em `main.py` (texto da task): `main.py` importa a CLI e a CLI importaria `main.py` → import circular #cli
- [decisao] Retry do modelo com `ModelRetryMiddleware(max_retries=2, retry_on=is_transient_model_error, on_failure="error")` no `create_agent`: `ConnectionError` (o cliente do Ollama troca o `httpx.ConnectError` por ele), `httpx.TransportError` e `ollama.ResponseError` 502/503/504 (o 500 do Ollama costuma ser permanente, ex.: falta de memória). `on_failure="error"`: senão o texto do erro viraria "resposta" do assistente no histórico #langchain
- [decisao] `OllamaFailureMiddleware` (mais externo, antes do retry) troca a falha transitória final por `OllamaConnectionError`: quem usa o agente recebe a hierarquia da app, e a CLI não precisa classificar exceções (achado do /code-review) #erros
- [licao] Retry no meio do streaming: a tentativa que falha não emite `on_chat_model_end`; a CLI zera o texto parcial no `on_chat_model_start` (`TurnRenderer.model_start`), senão a resposta aparecia duplicada (achado do /code-review) #cli
- [decisao] `ToolFailureMiddleware` (`awrap_tool_call` próprio) troca exceção não tratada de tool por `ToolExecutionError`, deixando passar `GraphBubbleUp` (interrupts). `isError` e argumentos inválidos continuam virando ToolMessage de erro antes, no ToolNode #langchain
- [alternativa-descartada] `ToolErrorMiddleware` embutido (langchain 1.4.7): só converte em ToolMessage ou deixa a exceção passar sem mudar o tipo #langchain
- [alternativa-descartada] `ToolRetryMiddleware`: servidor stdio que morre não volta com retry (mesma decisão da task 4) #mcp
- [decisao] Ollama checado uma vez só, antes de abrir o banco (falha rápida). Sem retry na inicialização: "modelo não baixado" não melhora com retry e o health não distingue os dois casos; as chamadas do modelo já têm retry #ollama
- [alternativa-descartada] `retry.retry_async` genérico (primeira versão): ficou com um uso só e duplicava o backoff do `DengueMCPClient` (achado do /code-review) #retry
- [licao] Não envolver `pool.open(wait=True)` do psycopg_pool em retry: o pool já reconecta com backoff (`AttemptWithBackoff`) até o timeout, e `PoolTimeout` é `OperationalError`. O retry externo era redundante e não multiplicava a espera como esperado. Timeout em `bootstrap.DB_CONNECT_TIMEOUT` (testes usam 1 s) #postgres
- [decisao] "Health endpoint" virou o comando `ai-agent-hospital health` (não há servidor HTTP): `health.health_check()` roda Ollama/banco/MCP em `asyncio.gather` (cada corrotina abre e fecha o MCP na própria task) e sai com 1 se algo falhar. `check_mcp_health` usa `max_retries=1` e `asyncio.timeout` em volta de tudo (servidor que trava no `list_tools` não prende o comando); `gather(return_exceptions=True)`: exceção não prevista numa checagem marca só aquele serviço como fora #health
- [decisao] SIGTERM: `cli._cancel_on_sigterm` cancela a task do comando; os `async with` fecham pools e o subprocesso MCP; exit 143, mesmo se o fechamento levantar erro #cli
- [convencao] `tests/test_bootstrap.py`: `open_session` real com Postgres em schema temporário, `fake_dengue_server.py` via stdio e LLM roteirizado (Ollama trocado por monkeypatch em `bootstrap.check_ollama_health`/`get_llm`); o SIGTERM é enviado de verdade com `os.kill` #testes
- [convencao] Testes do `ModelRetryMiddleware` zeram a espera com `monkeypatch.setattr(model_retry, "calculate_delay", ...)` (módulo `langchain.agents.middleware.model_retry`) #testes
- [licao] O `health` mostrou o `SMART_HOSPITALS_PATH` do `.env` local resolvendo dentro deste repo (sem `/` inicial?); por isso os e2e reais eram pulados. Com o path absoluto, health ok e e2e passam #config

## Relations
- part_of [[ai_agent_hospital]]
- depends_on [[CLI interativa]]
- depends_on [[Cliente MCP do servidor de dengue]]
